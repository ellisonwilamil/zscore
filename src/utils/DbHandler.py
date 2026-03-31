import psycopg2
from dotenv import load_dotenv
import os
from datetime import datetime
import logging

load_dotenv()

class AnomalyDatabaseHandler:
    def __init__(self):
        self.conn = None
        self.cursor = None
        self.connect()
    
    def connect(self):
        try:
            # Usando as variáveis unificadas
            self.conn = psycopg2.connect(
                host=os.getenv("DB_ADDRESS"),
                port=os.getenv("DB_PORT"),
                dbname=os.getenv("DB_NAME"),
                user=os.getenv("DB_USERNAME"),
                password=os.getenv("DB_PASSWORD")
            )
            self.cursor = self.conn.cursor()
            return True
        except Exception as e:
            logging.error(f"Erro na conexão com o banco (Schema AnalyticsAnomalies): {str(e)}")
            return False

    def insert_execution_summary(self, summary_data: dict):
        try:
            columns = ", ".join(summary_data.keys())
            placeholders = ", ".join(["%s"] * len(summary_data))
            
            # Referência explícita ao Schema
            query = f"""
            INSERT INTO "AnalyticsAnomalies".script_execution_summary ({columns})
            VALUES ({placeholders}) RETURNING id;
            """
            self.cursor.execute(query, list(summary_data.values()))
            inserted_id = self.cursor.fetchone()[0]
            self.conn.commit()
            return inserted_id
        except Exception as e:
            self.conn.rollback()
            return None

    def insert_anomaly(self, script_execution_id, machine_name, sensor_name, trend_name, 
                       anomaly_datetime, var_value=None, adaptive_threshold=None, 
                       diff_value=None, excess_percent=None, igas_value=None):
        try:
            # Query atualizada para o novo Schema
            insert_query = """
            INSERT INTO "AnalyticsAnomalies".anomalies (
                script_execution_id, machine_name, sensor_name, trend_name, anomaly_datetime,
                var_value, adaptive_threshold, diff_value, excess_percent, igas_value
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (machine_name, sensor_name, trend_name, anomaly_datetime) 
            DO UPDATE SET
                script_execution_id = EXCLUDED.script_execution_id,
                var_value = COALESCE(EXCLUDED.var_value, "AnalyticsAnomalies".anomalies.var_value),
                igas_value = COALESCE(EXCLUDED.igas_value, "AnalyticsAnomalies".anomalies.igas_value);
            """
            self.cursor.execute(insert_query, (
                script_execution_id, machine_name, sensor_name, trend_name, anomaly_datetime,
                var_value, adaptive_threshold, diff_value, excess_percent, igas_value
            ))
            self.conn.commit()
            return True
        except Exception as e:
            self.conn.rollback()
            return False

    def close(self):
        if self.cursor: self.cursor.close()
        if self.conn: self.conn.close()