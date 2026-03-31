import pandas as pd
import pytz

UTC_TZ = pytz.utc
SAO_PAULO_TZ = pytz.timezone('America/Sao_Paulo')

def standardize_to_utc(df):
    """Padroniza o DataFrame para UTC baseado na origem São Paulo."""
    if df is None or df.empty or 'DateTime' not in df.columns:
        return df
    
    df = df.copy()
    df['DateTime'] = pd.to_datetime(df['DateTime'])
    
    # Se o dado vem do banco sem fuso (Naive), assume SP e converte para UTC
    if df['DateTime'].dt.tz is None:
        df['DateTime'] = df['DateTime'].dt.tz_localize(SAO_PAULO_TZ).dt.tz_convert(UTC_TZ)
    else:
        # Se já tem fuso, apenas garante que seja UTC
        df['DateTime'] = df['DateTime'].dt.tz_convert(UTC_TZ)
        
    return df.sort_values("DateTime")