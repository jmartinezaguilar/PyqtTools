# -*- coding: utf-8 -*-
"""
Created on Tue Jun 23 12:01:55 2020

@author: lucia
"""

from PyQt5 import Qt
import numpy as np

import Pyxi.CalcPSD as PSD
import PyqtTools.SaveCharacterization_Class as SaveDicts


class StbDetThread(Qt.QThread):
    NextVg = Qt.pyqtSignal()
    NextVd = Qt.pyqtSignal()
    CharactEnd = Qt.pyqtSignal()

    def __init__(self, ACenable, VdVals, VgVals, MaxSlope, TimeOut, TimeBuffer, 
                 nChannels, ChnName, PlotterDemodKwargs):
        '''Initialization for Stabilitation Detection Thread
           VdVals: Array. Contains the values to use in the Vd Sweep.
                          [0.1, 0.2]
           VgVals: Array. Contains the values to use in the Vg Sweep
                          [0., -0.1, -0.2, -0.3]
           MaxSlope: float. Specifies the maximum slope permited to consider
                            the system is stabilazed, so the data is correct
                            to be acquired
           TimeOut: float. Specifies the maximum amount of time to wait the
                           signal to achieve MaxSlope, if TimeOut is reached
                           the data is save even it is not stabilazed
           nChannels: int. Number of acquisition channels (rows) active
           ChnName: dictionary. Specifies the name of Row+Column beign
                                processed and its index:
                                {'Ch04Col1': 0,
                                'Ch05Col1': 1,
                                'Ch06Col1': 2}
           PlotterDemodKwargs: dictionary. Contains Demodulation Configuration
                                           an parameters
                                           {'Fs': 5000.0,
                                           'nFFT': 8.0,
                                           'scaling': 'density',
                                           'nAvg': 50 }
        '''
        super(StbDetThread, self).__init__()
        self.threadCalcPSD = None
        self.ToStabData = None
        self.Stable = False
        self.Datos = None
        
        self.ACenable = ACenable
        self.MaxSlope = MaxSlope
        self.TimeOut = TimeOut

        self.VgIndex = 0
        self.VdIndex = 0

        self.Timer = Qt.QTimer()
        self.Timer.timeout.connect(self.printTime)

        self.Buffer = PltBuffer2D.Buffer2D(PlotterDemodKwargs['Fs'],
                                           nChannels,
                                           TimeBuffer)
        
        self.threadCalcPSD = PSD.CalcPSD(nChannels=nChannels,
                                         **PlotterDemodKwargs)
        self.threadCalcPSD.PSDDone.connect(self.on_PSDDone)
        self.SaveDCAC = SaveDicts.SaveDicts(SwVdsVals=VdVals,
                                            SwVgsVals=VgVals,
                                            Channels=ChnName,
                                            nFFT=int(PlotterDemodKwargs['nFFT']),
                                            FsDemod=PlotterDemodKwargs['Fs']
                                            )
        if self.ACenable:
            self.SaveDCAC.PSDSaved.connect(self.on_NextVgs)
        else:
            self.SaveDCAC.DCSaved.connect(self.on_NextVgs)

    def initTimer(self):
        self.Timer.timeout.connect(self.printTime)

    def run(self):
        while True:
            if self.Buffer.IsFilled():
                Data = self.Buffer
                for dat in Data.transpose():
                    r, c = dat.shape
                    x = np.arange(0, r)
                    mm, oo = np.polyfit(x, dat, 1)
                    Dev = np.abs(np.mean(mm))
                    print('Slope Calc -->', Dev)

                    if Dev < self.MaxSlope:
                        print('Final slope is -->', Dev)
                        self.Timer.stop()
                        self.Timer.timeout.disconnect()
                        self.DCIdCalc()

                self.Buffer.Reset()

            else:
                Qt.QThread.msleep(10)
            if self.ToStabData is not None:
                Data = self.ToStabData

                self.ToStabData = None

            else:
                Qt.QThread.msleep(10)

    def AddData(self, NewData):
        if self.Stable is False:
            self.Buffer.AddData(NewData)
            self.Datos = self.Buffer  # se guardan los datos para que no se sobreescriban
        if self.Stable is True:
            self.threadCalcPSD.AddData(NewData)

    def printTime(self):
        print('TimeOut')
        self.Timer.stop()
        self.Timer.timeout.disconnect()
        self.DCIdCalc()

    def DCIdCalc(self):
        self.Buffer.Reset()
        # se activa el flag de estable
        self.Stable = True
        # se activa el thread para calcular PSD
        if self.ACenable:
            self.threadCalcPSD.start()
        # se obtiene el punto para cada Row
        self.DCIds = np.ndarray((self.Datos.shape[1], 1))
        for ind in range(self.Datos.shape[1]):
            Data = np.abs(self.Datos[:, ind])
            x = np.arange(Data.size)
            self.ptrend = np.polyfit(x, Data, 1)

            self.DCIds[ind] = (self.ptrend[-1])  # Se toma el ultimo valor
        # Se guardan los valores DC
        self.SaveDCAC.SaveDCDict(Ids=self.DCIds,
                                 SwVgsInd=self.VgIndex,
                                 SwVdsInd=self.VdIndex)    

    def on_PSDDone(self):
        self.freqs = self.threadCalcPSD.ff
        self.PSDdata = self.threadCalcPSD.psd
        # se desactiva el thread para calcular PSD
        self.threadCalcPSD.stop()
        
        # Se guarda en AC dicts
        self.SaveDCAC.SaveACDict(psd=self.PSDdata,
                                 ff=self.freqs,
                                 SwVgsInd=self.VgIndex,
                                 SwVdsInd=self.VdIndex
                                 )

    def on_NextVgs(self):
        self.Stable = False
        self.VgIndex += 1
        if self.VgIndex < len(self.VgSweepVals):
            self.NextVgs = self.VgSweepVals[self.VgIndex]
            
            self.NextVg.emit()
        else:
            self.VgIndex = 0
            self.on_NextVds()

    def on_NextVds(self):
        self.VdIndex += 1
        
        if self.VdIndex < len(self.VdSweepVals):
            self.NextVds = self.VdSweepVals[self.VdIndex]
            
            self.NextVd.emit()

        else:
            self.VdIndex = 0
            self.NextVg.disconnect()
            self.NextVd.disconnect()
            
            self.DCDict = self.SaveDCAC.DevDCVals
            self.ACDict = self.SaveDCAC.DevACVals
            self.CharactEnd.emit()
        
            
    def stop(self):
        self.threadCalcPSD.PSDDone.disconnect()
        self.SaveDCAC.PSDSaved.disconnect()
        if self.threadCalcPSD is not None:
            self.threadCalcPSD.stop()
        self.terminate()