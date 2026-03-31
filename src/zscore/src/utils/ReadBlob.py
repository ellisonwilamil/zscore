# -*- coding: utf-8 -*-
from typing import Union
import struct
import itertools
import datetime
import pandas as pd
import numpy as np
import sys

# Impedindo a geração do __pycache__
sys.dont_write_bytecode = True

# =============================================================================
# MÉTODOS MODERNOS (NUMPY / VETORIZADO) - Padrão para Scripts (Alta Performance)
# =============================================================================

def ReadBlob_Vectorized(blob: memoryview, blobType:str = 'd') -> np.ndarray:
    """
    Função otimizada para ler os blobs usando vetorização NumPy.
    Velocidade ~30x superior.
    """
    dtype_map = {
        'd': np.float64,
        'f': np.float32,
        'q': np.int64,
        '?': np.bool_
    }
    
    dt = dtype_map.get(blobType)
    if dt is None:
        raise ValueError(f'Unknown type of blob: {blobType}')
    
    return np.frombuffer(blob, dtype=dt).astype(np.float64)

def ReadTrendSignalRecordsBlobs_Vectorized(df: pd.DataFrame, 
                                blobsColumns: list[str] = ["SamplesDateTime", "SamplesValues"],
                                blobsType: list[str] = ['q','f'],
                                newColumns: list[str] = ["DateTime", "Value"],
                                uselessCols: list[str] = ['YearAndMonth']) -> pd.DataFrame:
    """
    Processamento vetorizado de blobs. Alta performance para scripts em lote.
    """
    if len(blobsColumns) != len(blobsType) or len(blobsColumns) != len(newColumns):
        raise ValueError("blobsColumns, blobsType e newColumns devem ter o mesmo tamanho!")

    if df.empty:
        cols = [c for c in df.columns if c not in blobsColumns + uselessCols] + newColumns
        return pd.DataFrame(columns=cols)

    dataraw = df[blobsColumns]
    
    parsed_data = {}
    lengths = None
    
    for k, col in enumerate(blobsColumns):
        arrays = dataraw[col].apply(lambda x: ReadBlob_Vectorized(x, blobType=blobsType[k]))
        parsed_data[newColumns[k]] = arrays
        if lengths is None:
            lengths = arrays.map(len).values

    repeated_indices = np.repeat(df.index.values, lengths)
    cols_to_keep = [c for c in df.columns if c not in blobsColumns + uselessCols]
    expanded_df = df.loc[repeated_indices, cols_to_keep].reset_index(drop=True)

    for new_col_name, arrays_series in parsed_data.items():
        flat_values = np.concatenate(arrays_series.values)
        
        if "DateTime" in new_col_name:
            base_date = np.datetime64('0001-01-01 00:00:00')
            try:
                # Conversão vetorizada de Ticks .NET
                timedeltas = (flat_values // 10).astype('timedelta64[us]')
                expanded_df[new_col_name] = base_date + timedeltas
            except:
                expanded_df[new_col_name] = pd.to_datetime(flat_values)
        else:
            expanded_df[new_col_name] = flat_values        

    return expanded_df

# =============================================================================
# MÉTODOS LEGADOS (STRUCT / LOOP) - Para compatibilidade com Telas (Robustez)
# =============================================================================

def ReadBlob_Legacy(blob: memoryview, blobType:str = 'd') -> list:
    """
    Função legado (lenta, baseada em struct).
    """
    valuesList = []
    if blobType == 'f': buf = 4
    elif blobType == 'd': buf = 8
    elif blobType == 'q': buf = 8
    elif blobType == '?': buf = 1
    else: raise Warning('Unknown type of blob.')
    
    nv = int(len(bytearray(blob))/buf)

    for k in range(nv):
        valuesList.append(struct.unpack(blobType,bytearray(blob[k*buf:(k*buf+buf)]))[0])
    return valuesList

def ReadTrendSignalRecordsBlobs_Legacy(df: pd.DataFrame, 
                                blobsColumns: list[str] = ["SamplesDateTime", "SamplesValues"],
                                blobsType: list[str] = ['q','f'],
                                newColumns: list[str] = ["DateTime", "Value"],
                                uselessCols: list[str] = ['YearAndMonth']) -> pd.DataFrame:
    """
    Processamento legado via loops e merges.
    Mais lento, mas evita problemas de buffer/duplicação específicos do numpy em certas versões de DB.
    """
    if len(blobsColumns) != len(blobsType) or len(blobsColumns) != len(newColumns):
        raise ValueError("Len mismatch")

    if df.empty:
         cols = [c for c in df.columns if c not in blobsColumns + uselessCols] + newColumns
         return pd.DataFrame(columns=cols)

    dataraw = df[blobsColumns].copy()
    data = df.drop(blobsColumns + uselessCols, axis=1).copy()

    for k in range(len(blobsColumns)):
        samples = dataraw[blobsColumns[k]].apply(lambda xrow: ReadBlob_Legacy(blob=xrow, blobType=blobsType[k]))
        
        ds = pd.DataFrame(data = list(itertools.chain.from_iterable(samples.to_list())), columns = [newColumns[k]])
        
        nSamplesDf = samples.apply(len)
        nSamplesDf.index.set_names('RawIndex',inplace=True)
        nSamplesDf = nSamplesDf.reset_index()
        nSamplesDf = nSamplesDf.reindex(nSamplesDf.index.repeat(nSamplesDf[blobsColumns[k]])).reset_index(drop =True)
        nSamplesDf = nSamplesDf.merge(ds, left_index=True, right_index=True)

        if blobsColumns[k] == "SamplesDateTime":
            nSamplesDf[newColumns[k]] = nSamplesDf[newColumns[k]].apply(
                lambda x: datetime.datetime(1, 1, 1, 0,0,0) + datetime.timedelta(microseconds=x // 10)
            )
                
        if k==0:
            auxDf = nSamplesDf[['RawIndex',newColumns[k]]].copy().reset_index()
        else:
            auxDf = auxDf.merge(nSamplesDf[['RawIndex',newColumns[k]]].reset_index(), on = ["index","RawIndex"])
    
    data.index.set_names('RawIndex',inplace=True)
    data.reset_index(inplace = True)
    data = data.merge(auxDf, on='RawIndex')
    data.drop(['RawIndex','index'], axis=1, inplace=True)
    
    return data

# =============================================================================
# EXPORTAÇÃO PADRÃO
# =============================================================================

# Por padrão, quem importar ReadBlob usará a versão RÁPIDA (Vetorizada).
# O arquivo anomalies_detection.py fará o override manual.
ReadBlob = ReadBlob_Vectorized
ReadTrendSignalRecordsBlobs = ReadTrendSignalRecordsBlobs_Vectorized

def ConvertSignalType(signalType: int = 3, singlePrecision: bool = False) -> str:
    if signalType == 6: return 'f'
    elif signalType == 3: return 'f' if singlePrecision else 'd'
    elif signalType == 1: return '?'
    else: return 'Unknown'

