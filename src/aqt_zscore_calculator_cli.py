import pandas as pd
from datetime import datetime, timedelta
from tqdm import tqdm
import logging
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import os
from urllib.parse import quote_plus
import argparse
import sys
import pytz

# Configuração do fuso horário
UTC = pytz.timezone('America/Sao_Paulo')

from utils.DatabaseQueries import DatabaseQueries
from utils.ZScoreCalculator import ZScoreCalculator

# Import para o banco de dados ZScore
sys.path.append('utils')
try:
    from utils.ZScoreDbHandler import ZScoreDatabaseHandler
except ImportError:
    print("❌ ZScoreDbHandler não encontrado. Verifique o caminho.")
    sys.exit(1)

logger = logging.getLogger(__name__)

logging.basicConfig(
    filename='aqt_zscore_calc.log',
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)

# ============================================================================
# CLASSE DE DEBUG
# ============================================================================
class DebugTracker:
    """Classe para rastrear e reportar informações de debug"""
    def __init__(self):
        self.aqt_sensors_processed = []
        self.aqt_trends_processed = []        
   
    def log_aqt_sensor(self, sensor, park):
        self.aqt_sensors_processed.append({'sensor': sensor, 'park': park})
        
    def log_aqt_trend(self, trend, park):
        self.aqt_trends_processed.append({'trend': trend, 'park': park})
        
    def print_summary(self):
        print("\n" + "="*80)
        print("📊 RELATÓRIO DE DEBUG DETALHADO")
        print("="*80)              
        print(f"\n📡 SENSORES AQT PROCESSADOS: {len(self.aqt_sensors_processed)}")
        print(f"📈 TENDÊNCIAS AQT PROCESSADAS: {len(self.aqt_trends_processed)}")
        print("="*80 + "\n")

# ============================================================================
# FUNÇÕES AUXILIARES
# ============================================================================

def setup_argument_parser():
    parser = argparse.ArgumentParser(
        description="Executa o cálculo de Z-Score comparativo (AQT).",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        '-d', '--data',
        dest='end_date',
        type=str,
        help="Data final da análise (YYYY-MM-DD)."
    )
    parser.add_argument('--config-name', dest='config_name', type=str)
    parser.add_argument('--window', dest='window_size', type=int)
    parser.add_argument('--multiplier', dest='multiplier', type=float)
    return parser

# MODIFICADO: Engine unificada de produção
def get_main_db_engine():
    """Conecta ao banco de dados principal de produção"""
    load_dotenv()
    try:
        conn_str = (
            f"postgresql://{os.getenv('DB_USERNAME')}:"
            f"{quote_plus(os.getenv('DB_PASSWORD'))}@"
            f"{os.getenv('DB_ADDRESS')}:{os.getenv('DB_PORT')}/"
            f"{os.getenv('DB_NAME')}"
        )
        return create_engine(conn_str)
    except Exception as e:
        logger.error(f"Erro ao criar engine de conexão: {e}")
        return None

def create_or_get_config(zscore_db, args):
    if args.config_name and args.window_size and args.multiplier:
        print(f"⚙️  Tentando criar nova configuração '{args.config_name}'...")
        config_data = {
            'config_name': args.config_name,
            'window_size_days': args.window_size,
            'zscore_std_multiplier': args.multiplier,
            'step_size_days': 1,
            'is_active': True
        }
        new_config = zscore_db.create_and_activate_config(config_data)
        if new_config:
            print(f"✅ Nova configuração '{args.config_name}' ativada.")
            return new_config
    else:
        config = zscore_db.get_active_config()
        if not config:
            print("⚠️  Nenhuma configuração ativa. Criando padrão...")
            config_data = {
                'config_name': 'default',
                'window_size_days': 7,
                'zscore_std_multiplier': 3.0,
                'step_size_days': 1,
                'is_active': True
            }
            config = zscore_db.create_and_activate_config(config_data)
        return config

def extract_park_from_machine(machine_name):
    if '-' in machine_name:
        return machine_name.split('-')[0]
    return 'DEFAULT_PARK'

def process_sensor_data(db_queries, machine_name, sensor_name, full_start_str, full_end_str):
    try:
        df_raw, df_processed = db_queries.carregar_dados_tendencia(
            machine_name, sensor_name, full_start_str, full_end_str
        )
        if df_processed is None or df_processed.empty:
            return None
        if not pd.api.types.is_datetime64_any_dtype(df_processed['DateTime']):
            df_processed['DateTime'] = pd.to_datetime(df_processed['DateTime'])
        if df_processed['DateTime'].dt.tz is None:
            df_processed['DateTime'] = df_processed['DateTime'].dt.tz_localize(UTC)
        else:
            df_processed['DateTime'] = df_processed['DateTime'].dt.tz_convert(UTC)
        df_processed['Value'] = pd.to_numeric(df_processed['Value'], errors='coerce')
        df_processed['Equipamento'] = machine_name
        return df_processed
    except Exception as e:
        logger.error(f"Erro em {machine_name}::{sensor_name}: {e}")
        return None

def prepare_trend_data_for_zscore(trend_df, machine_name):
    if trend_df.empty: return pd.DataFrame()
    calculation_df = trend_df[['DateTime', 'Value']].copy()
    calculation_df['Equipamento'] = machine_name
    calculation_df['DateTime'] = pd.to_datetime(calculation_df['DateTime'])
    calculation_df['Value'] = pd.to_numeric(calculation_df['Value'], errors='coerce')
    calculation_df.dropna(subset=['Value'], inplace=True)
    return calculation_df

# MODIFICADO: Verificação de tabela agora aponta para o Schema AnalyticsZscore
def verify_table_exists(zscore_db_handler):
    if not zscore_db_handler or not zscore_db_handler.conn:
        return False
    try:
        with zscore_db_handler.conn.cursor() as conn_cursor:
            conn_cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_schema = 'AnalyticsZscore' 
                    AND table_name = 'zscore_results'
                );
            """)
            table_exists = conn_cursor.fetchone()[0]
            print(f"📋 Tabela AnalyticsZscore.zscore_results existe: {table_exists}")
            return table_exists
    except Exception as e:
        print(f"❌ Erro ao verificar tabela: {e}")
        return False

# ============================================================================
# FUNÇÃO PRINCIPAL
# ============================================================================

def run_zscore_calculation(end_date_str: str = None, args=None):
    start_run_time = datetime.now()
    debug_tracker = DebugTracker()
    
    print("\n" + "="*60)
    print("🚀 INICIANDO CÁLCULO DE Z-SCORE COMPARATIVO (PRODUÇÃO)")
    print("="*60)

    main_engine = get_main_db_engine()
    zscore_db = ZScoreDatabaseHandler()

    if not main_engine or not zscore_db.conn:
        print("❌ Falha crítica nas conexões. Abortando.")
        if zscore_db: zscore_db.close()
        return

    verify_table_exists(zscore_db)

    config = create_or_get_config(zscore_db, args)
    if not config:
        zscore_db.close()
        return

    if end_date_str:
        try:
            data_final_dt = datetime.strptime(end_date_str, "%Y-%m-%d").replace(hour=0, minute=0, second=0)
        except ValueError:
            print(f"❌ Data inválida: {end_date_str}")
            zscore_db.close()
            sys.exit(1)
    else:
        data_final_dt = datetime.now().replace(hour=0, minute=0, second=0)

    print(f"🗓️  Data final da análise: {data_final_dt.strftime('%Y-%m-%d')}")

    full_end_dt_naive = data_final_dt + timedelta(days=1)
    window_days = int(config.get('window_size_days', 7))
    window_days_guaranteed = max(window_days, 31) 
    full_start_dt_naive = full_end_dt_naive - timedelta(days=window_days_guaranteed)

    full_start_str = full_start_dt_naive.strftime('%Y.%m.%d')
    full_end_str = full_end_dt_naive.strftime('%Y.%m.%d')

    print(f"🔍 Período de busca: {full_start_str} a {full_end_str}")

    db_queries = DatabaseQueries(main_engine)
    zscore_calculator = ZScoreCalculator()
    
    execution_id = zscore_db.insert_execution_summary(
        start_run_time, config['id'], schemas='aqt', date_filter=data_final_dt.date()
    )
    
    if not execution_id:
        zscore_db.close()
        return

    zscore_config = {'window_size_days': window_days, 'zscore_std_multiplier': config['zscore_std_multiplier']}
    summary_stats = {"processed_parks": 0, "processed_machines": 0, "processed_sensors": 0, "processed_trends": 0, "zscore_records_inserted": 0, "status": "Running"}

    try:
        machines_df = db_queries.carregar_maquinas()
        if machines_df.empty:
            parks = {}
        else:
            all_machines = machines_df['Name'].tolist()
            parks = {}
            for machine in all_machines:
                park_name = extract_park_from_machine(machine)
                if park_name not in parks: parks[park_name] = []
                parks[park_name].append(machine)

            summary_stats["processed_parks"] = len(parks)
            summary_stats["processed_machines"] = len(all_machines)

        for park_name, machines_in_park in tqdm(parks.items(), desc="🌀 Processando Parques", unit="parque"):
            reference_machine = machines_in_park[0]
            sensors_df = db_queries.carregar_sensores(reference_machine)

            if not sensors_df.empty:
                for sensor_row in tqdm(sensors_df.itertuples(), desc=f"📡 Sensores em {park_name}", leave=False, total=len(sensors_df)):
                    sensor_name = sensor_row.sensor_name
                    if sensor_name == 'REF': continue
                    
                    summary_stats["processed_sensors"] += 1
                    debug_tracker.log_aqt_sensor(sensor_name, park_name)

                    all_machine_data_for_sensor = []
                    for machine_name in machines_in_park:
                        df_processed = process_sensor_data(db_queries, machine_name, sensor_name, full_start_str, full_end_str)
                        if df_processed is not None and not df_processed.empty:
                            all_machine_data_for_sensor.append(df_processed)

                    if not all_machine_data_for_sensor: continue

                    combined_df = pd.concat(all_machine_data_for_sensor, ignore_index=True)
                    available_trends = combined_df['Tendencia'].unique()

                    for trend_name in available_trends:
                        summary_stats["processed_trends"] += 1
                        debug_tracker.log_aqt_trend(trend_name, park_name)

                        trend_df = combined_df[combined_df['Tendencia'] == trend_name].copy()
                        all_machines_trend_data = [prepare_trend_data_for_zscore(trend_df[trend_df['Equipamento'] == m], m) for m in machines_in_park if not trend_df[trend_df['Equipamento'] == m].empty]

                        if not all_machines_trend_data: continue

                        calculation_df = pd.concat(all_machines_trend_data, ignore_index=True)
                        zscore_result_df = zscore_calculator.calculate_comparative_zscore(calculation_df, data_final_dt, zscore_config)

                        if not zscore_result_df.empty:
                            zscore_result_df['execution_id'] = execution_id
                            zscore_result_df['park_name'] = park_name
                            zscore_result_df['sensor_name'] = sensor_name
                            zscore_result_df['trend_name'] = trend_name

                            inserted_count = zscore_db.insert_zscore_results_directly(zscore_result_df, trend_name)
                            summary_stats["zscore_records_inserted"] += inserted_count

        execution_duration = (datetime.now() - start_run_time).total_seconds()
        zscore_db.update_execution_summary(execution_id, {
            'end_time': datetime.now(), 'execution_time_seconds': execution_duration, 'status': 'Completed',
            'processed_parks': summary_stats['processed_parks'], 'processed_machines': summary_stats['processed_machines'],
            'processed_sensors': summary_stats['processed_sensors'], 'processed_trends': summary_stats['processed_trends'],            
            'zscore_records_inserted': summary_stats['zscore_records_inserted']
        })
        debug_tracker.print_summary()

    except Exception as e:
        logger.error(f"❌ ERRO FATAL: {e}", exc_info=True)
        zscore_db.update_execution_summary(execution_id, {'status': 'Failed', 'error_log': str(e)})

    finally:
        zscore_db.close()

if __name__ == "__main__":
    arg_parser = setup_argument_parser()
    args = arg_parser.parse_args()
    run_zscore_calculation(end_date_str=args.end_date, args=args)