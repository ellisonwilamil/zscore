import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
import os
import pandas as pd
from sqlalchemy import create_engine

load_dotenv()

class ZScoreDatabaseHandler:
    def __init__(self):
        self.conn = None
        try:
            # Conexão unificada
            self.conn = psycopg2.connect(
                host=os.getenv("DB_ADDRESS"),
                port=os.getenv("DB_PORT"),
                dbname=os.getenv("DB_NAME"),
                user=os.getenv("DB_USERNAME"),
                password=os.getenv("DB_PASSWORD")
            )
            # Engine unificada para Pandas
            conn_uri = f"postgresql+psycopg2://{os.getenv('DB_USERNAME')}:{os.getenv('DB_PASSWORD')}@{os.getenv('DB_ADDRESS')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
            self.engine = create_engine(conn_uri, pool_pre_ping=True)
            self.cursor = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        except Exception as e:
            logging.error(f"Erro na conexão Z-Score (Schema AnalyticsZscore): {str(e)}")

    def get_active_config(self) -> dict:
        if not self.conn: return None
        try:
            # Busca no Schema específico
            self.cursor.execute('SELECT * FROM "AnalyticsZscore".zscore_configs WHERE is_active = TRUE LIMIT 1;')
            config = self.cursor.fetchone()
            return dict(config) if config else None
        except Exception as e:
            return None

    def insert_zscore_results_directly(self, zscore_result_df: pd.DataFrame, trend_name: str) -> int:
        if not self.conn or zscore_result_df.empty: return 0
        
        required_columns = [
            'machine_name', 'window_end_date', 'z_score', 'variance', 'base_fixa',
            'group_mean_base_fixa', 'group_std_base_fixa', 'execution_id',
            'park_name', 'sensor_name', 'trend_name' 
        ]
        zscore_result_df = zscore_result_df.reindex(columns=required_columns)

        try:
            data_tuples = [tuple(x) for x in zscore_result_df.to_numpy()]
            update_cols = ['z_score', 'variance', 'base_fixa', 'group_mean_base_fixa', 'group_std_base_fixa', 'execution_id']
            update_clause = ", ".join([f"{col} = EXCLUDED.{col}" for col in update_cols])

            # Inserção direta no Schema AnalyticsZscore
            insert_query = f"""
            INSERT INTO "AnalyticsZscore".zscore_results ({', '.join(required_columns)})
            VALUES %s
            ON CONFLICT (park_name, machine_name, sensor_name, trend_name, window_end_date)
            DO UPDATE SET {update_clause};
            """
            psycopg2.extras.execute_values(self.cursor, insert_query, data_tuples)
            self.conn.commit()
            return self.cursor.rowcount
        except Exception as e:
            self.conn.rollback()
            return 0

    def close(self):
        if self.conn: self.conn.close()
        if hasattr(self, 'engine'): self.engine.dispose()