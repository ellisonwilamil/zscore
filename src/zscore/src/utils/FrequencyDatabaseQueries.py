import pandas as pd
from utils.ReadBlob import ReadTrendSignalRecordsBlobs

class FrequencyDatabaseQueries:
    """
    Classe para lidar com as consultas relacionadas aos dados de frequência 
    no schema 'FrequencyTrends' do banco de dados.
    """
    def __init__(self, conn):
        self.conn = conn

    def carregar_maquinas(self):
        """Carrega a lista de máquinas (GeneratingUnits) disponíveis para frequência."""
        query = '''
        SELECT DISTINCT "GeneratingUnitName" AS "Name"
        FROM "FrequencyTrends"."GeneratingUnits"
        ORDER BY "Name" ASC;
        '''
        return pd.read_sql_query(query, self.conn)

    def carregar_todas_tendencias_disponiveis(self):
        """
        Carrega todas as tendências de frequência disponíveis com suas máquinas associadas.
        
        Faz o JOIN entre:
        - FrequencySettings (TAG da tendência)
        - SpectrumSettings (intermediária)
        - Signals (SignalName e associação com máquina)
        - GeneratingUnits (Nome da máquina)
        
        Returns:
            DataFrame com colunas: Tendencia, Machine, SignalName, SignalSettingId, FrequencySettingId
        """

        
        query = '''
        SELECT DISTINCT 
            fs."TAG" AS "Tendencia",
            gu."GeneratingUnitName" AS "Machine",
            sig."SignalName" AS "SignalName",
            sig."SignalSettingId" AS "SignalSettingId",
            fs."Id" AS "FrequencySettingId"
        FROM "FrequencyTrends"."FrequencySettings" AS fs
        JOIN "FrequencyTrends"."SpectrumSettings" AS ss
            ON fs."SpectrumSettingId" = ss."Id"
        JOIN "FrequencyTrends"."Signals" AS sig
            ON ss."SignalSettingId" = sig."SignalSettingId"
        JOIN "FrequencyTrends"."GeneratingUnits" AS gu
            ON sig."GeneratingUnitMonitoringElementId" = gu."MonitoringElementId"
        ORDER BY gu."GeneratingUnitName" ASC, fs."TAG" ASC;
        '''
        # --- FIM DA CORREÇÃO ---
        return pd.read_sql_query(query, self.conn)
    
    def carregar_tendencias_por_parque(self, park_name):
        """
        Carrega tendências de frequência filtradas por parque.
        
        Args:
            park_name: Nome do parque (ex: 'AND', 'SER', 'CF1')
        
        Returns:
            DataFrame com colunas: Tendencia, Machine, SignalName
        """  
        query = f'''
        SELECT DISTINCT 
            fs."TAG" AS "Tendencia",
            gu."GeneratingUnitName" AS "Machine",
            sig."SignalName" AS "SignalName",
            fs."Id" AS "FrequencySettingId"
        FROM "FrequencyTrends"."FrequencySettings" AS fs
        JOIN "FrequencyTrends"."SpectrumSettings" AS ss
            ON fs."SpectrumSettingId" = ss."Id"
        JOIN "FrequencyTrends"."Signals" AS sig
            ON ss."SignalSettingId" = sig."SignalSettingId"
        JOIN "FrequencyTrends"."GeneratingUnits" AS gu
            ON sig."GeneratingUnitMonitoringElementId" = gu."MonitoringElementId"
        WHERE gu."GeneratingUnitName" LIKE '{park_name}-%'
        ORDER BY gu."GeneratingUnitName" ASC, fs."TAG" ASC;
        '''
        # --- FIM DA CORREÇÃO ---
        return pd.read_sql_query(query, self.conn)

    def carregar_dados_tendencia_especifica(self, tendencia_tag, inicio, fim):
        """
        Carrega e processa dados de blob para uma tendência de frequência 
        específica (TAG) em um determinado período.
        """
        query = f"""
        SELECT 
            ftb."Id",
            ftb."FrequencySettingId",
            ftb."Year",
            ftb."DateTime" AS "SamplesDateTime", -- Coluna 'DateTime' da tabela ftb é o blob de data/hora
            ftb."Value" AS "SamplesValues",      -- Coluna 'Value' da tabela ftb é o blob de valores
            fs."TAG" AS "Tendencia"
        FROM "FrequencyTrends"."FrequencyTrendsBlobs" AS ftb
        JOIN "FrequencyTrends"."FrequencySettings" AS fs
            ON ftb."FrequencySettingId" = fs."Id"
        WHERE
            fs."TAG" = '{tendencia_tag}'
            AND ftb."Year" BETWEEN EXTRACT(YEAR FROM DATE '{inicio}') AND EXTRACT(YEAR FROM DATE '{fim}')
        ORDER BY ftb."Year" DESC
        """
        
        df_raw = pd.read_sql_query(query, self.conn)

        if df_raw.empty:
            return df_raw, pd.DataFrame()

        # Decodifica os blobs
        # os blobs de data/hora são 'q' (long long) e os de valor são 'f' (float)
        df_processado = ReadTrendSignalRecordsBlobs(
            df=df_raw,
            blobsColumns=["SamplesDateTime", "SamplesValues"],
            blobsType=['q', 'f'],
            newColumns=["DateTime", "Value"],
            uselessCols=['Year'] 
        )
        
        # Filtra pelo período de data/hora após a decodificação do blob
        df_processado['DateTime'] = pd.to_datetime(df_processado['DateTime'])
        
        # Garante que as datas de início e fim sejam datetime
        inicio_dt = pd.to_datetime(inicio)
        fim_dt = pd.to_datetime(fim)
        
        mask = (df_processado['DateTime'] >= inicio_dt) & (df_processado['DateTime'] <= fim_dt)
        df_filtrado = df_processado[mask]

        return df_raw, df_filtrado
