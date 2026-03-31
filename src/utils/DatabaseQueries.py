import pandas as pd
from utils.ReadBlob import ReadTrendSignalRecordsBlobs_Vectorized, ReadTrendSignalRecordsBlobs_Legacy
from datetime import date

class DatabaseQueries:
    def __init__(self, conn):
        self.conn = conn

    def obter_limites_globais_datas(self):
        """
        Busca o mês mais antigo e o mais recente na tabela.
        Como a tabela só tem referência de Mês/Ano, calculamos o último dia
        do mês final para garantir que todo o período seja coberto.
        """
        # Voltamos a usar YearAndMonth, pois DateTime não existe na tabela bruta
        query = '''
            SELECT 
                MIN("YearAndMonth") as data_inicio, 
                MAX("YearAndMonth") as data_fim 
            FROM "AQT"."TrendSignalRecords";
        '''
        try:
            df = pd.read_sql_query(query, self.conn)
            
            if not df.empty and pd.notna(df['data_inicio'].iloc[0]):
                min_date = pd.to_datetime(df['data_inicio'].iloc[0]).date()
                max_month_start = pd.to_datetime(df['data_fim'].iloc[0]).date()
                
                # Lógica para pegar o FINAL do mês máximo encontrado
                # Se o banco diz "2025-02-01", queremos liberar até "2025-02-28"
                # Avança 32 dias para cair no próximo mês, depois volta para o dia 1 e subtrai 1 dia
                next_month = max_month_start + pd.Timedelta(days=32)
                max_date = next_month.replace(day=1) - pd.Timedelta(days=1)
                
                return min_date, max_date
            else:
                # Fallback
                from datetime import date
                return date(2023, 1, 1), date.today()
                
        except Exception as e:
            print(f"Erro ao buscar datas globais: {e}")
            from datetime import date
            return date(2023, 1, 1), date.today()

    def carregar_maquinas(self):
        """Carrega a lista de máquinas disponíveis."""
        query = '''
            SELECT DISTINCT "Name" 
            FROM "AQT"."MonitoringElements" 
            WHERE "Name" ~ '^[A-Z]{2}.-\\d{2}$'
            ORDER BY "Name" ASC;
        '''
        return pd.read_sql_query(query, self.conn)

    def carregar_sensores(self, maquina):
        """Carrega os sensores disponíveis para uma máquina específica."""
        query = f'''
            SELECT DISTINCT "Sensor"."Name" AS sensor_name
            FROM "AQT"."MonitoringElements" AS "Equipamento",
                 "AQT"."MonitoringElements" AS "Categoria",
                 "AQT"."MonitoringElements" AS "Sensor",
                 "AQT"."MonitoringElements" AS "Tendencia"
            WHERE "Tendencia"."MonitoringElementParentId" = "Sensor"."Id"
              AND "Sensor"."MonitoringElementParentId" = "Categoria"."Id"
              AND "Categoria"."MonitoringElementParentId" = "Equipamento"."Id"
              AND "Equipamento"."Name" = '{maquina}'
              AND "Sensor"."Name" <> 'Modbus'
            ORDER BY sensor_name;
        '''
        return pd.read_sql_query(query, self.conn)

    def carregar_dados_tendencia(self, maquina, sensor, inicio, fim, use_legacy_reader: bool = False):
        """Carrega e processa os dados de tendência."""
        query = f"""
        SELECT "AQT"."TrendSignalRecords".*, "AQT"."TrendSignalSettings"."Name" AS "Tendencia"
        FROM "AQT"."TrendSignalRecords"
        JOIN "AQT"."TrendSignalSettings"
          ON "AQT"."TrendSignalRecords"."TrendSignalSettingId" = "AQT"."TrendSignalSettings"."Id"
        WHERE "TrendSignalSettingId" IN (
            SELECT "Id" 
            FROM "AQT"."TrendSignalSettings"
            WHERE "MonitoringElementId" IN (
                SELECT "Tendencia"."Id" 
                FROM "AQT"."MonitoringElements" AS "Equipamento", 
                     "AQT"."MonitoringElements" AS "Categoria", 
                     "AQT"."MonitoringElements" AS "Sensor", 
                     "AQT"."MonitoringElements" AS "Tendencia"
                WHERE "Tendencia"."MonitoringElementParentId" = "Sensor"."Id"
                  AND "Sensor"."MonitoringElementParentId" = "Categoria"."Id"
                  AND "Categoria"."MonitoringElementParentId" = "Equipamento"."Id"
                  AND "Equipamento"."Name" = '{maquina}' 
                  AND "Sensor"."Name" = '{sensor}'
            )
        )
        AND "YearAndMonth" BETWEEN '{inicio}' AND '{fim}';
        """

        df_raw = pd.read_sql_query(query, self.conn)

        # return df_raw, ReadTrendSignalRecordsBlobs(df_raw, uselessCols=['YearAndMonth','MeanValuesByDay'])
        if use_legacy_reader:
            # print("INFO: Usando leitor de blob LEGADO para a requisição da UI.")
            return df_raw, ReadTrendSignalRecordsBlobs_Legacy(df_raw, uselessCols=['YearAndMonth','MeanValuesByDay'])
        else:
            # O comportamento padrão (para scripts) continua sendo o método rápido
            return df_raw, ReadTrendSignalRecordsBlobs_Vectorized(df_raw, uselessCols=['YearAndMonth','MeanValuesByDay'])


    def carregar_dados_modbus(self, maquina, inicio, fim):
        """Carrega e processa os dados Modbus."""
        query = f"""
        SELECT "AQT"."TrendSignalRecords".*, "AQT"."TrendSignalSettings"."Name" AS "Tendencia"
        FROM "AQT"."TrendSignalRecords"
        JOIN "AQT"."TrendSignalSettings"
          ON "AQT"."TrendSignalRecords"."TrendSignalSettingId" = "AQT"."TrendSignalSettings"."Id"
        WHERE "TrendSignalSettingId" IN (
            SELECT "Id" 
            FROM "AQT"."TrendSignalSettings"
            WHERE "MonitoringElementId" IN (
                SELECT "Tendencia"."Id" 
                FROM "AQT"."MonitoringElements" AS "Equipamento", 
                     "AQT"."MonitoringElements" AS "Categoria", 
                     "AQT"."MonitoringElements" AS "Sensor", 
                     "AQT"."MonitoringElements" AS "Tendencia"
                WHERE "Tendencia"."MonitoringElementParentId" = "Sensor"."Id"
                  AND "Sensor"."MonitoringElementParentId" = "Categoria"."Id"
                  AND "Categoria"."MonitoringElementParentId" = "Equipamento"."Id"
                  AND "Equipamento"."Name" = '{maquina}' 
                  AND "Sensor"."Name" = 'Modbus'
            )
        )
        AND "YearAndMonth" BETWEEN '{inicio}' AND '{fim}';
        """
        df_raw = pd.read_sql_query(query, self.conn)
        return df_raw, ReadTrendSignalRecordsBlobs_Vectorized(df_raw, uselessCols=['YearAndMonth','MeanValuesByDay'])
