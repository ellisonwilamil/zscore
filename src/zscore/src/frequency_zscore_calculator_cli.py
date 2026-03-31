import pandas as pd
from datetime import datetime, timedelta
from tqdm import tqdm
import logging
from sqlalchemy import create_engine
from dotenv import load_dotenv
import os
from urllib.parse import quote_plus
import argparse
import sys
import pytz
import numpy as np

# Configuração do fuso horário
UTC = pytz.timezone('America/Sao_Paulo')

# Configuração global de precisão do Pandas para visualização
pd.set_option('display.float_format', lambda x: '%.8f' % x) 

from utils.DatabaseQueries import DatabaseQueries
from utils.FrequencyDatabaseQueries import FrequencyDatabaseQueries
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
    filename='frequency_zscore_calc.log',
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)

# ============================================================================
# CLASSE DE DEBUG E RASTREAMENTO
# ============================================================================
class DebugTracker:
    def __init__(self):
        self.freq_trends_processed = [] 
        self.freq_tags_skipped = []     
        self.freq_tags_failed = []      
        self.total_records_read = 0
        
    def log_success(self, trend_name, record_count):
        self.freq_trends_processed.append({'trend': trend_name, 'count': record_count})
        self.total_records_read += record_count

    def log_skipped(self, tag, reason):
        self.freq_tags_skipped.append({'tag': tag, 'reason': reason})

    def log_failed(self, tag, error):
        self.freq_tags_failed.append({'tag': tag, 'error': str(error)})
   
    def print_summary(self):
        print("\n" + "="*80)
        print("📊 RELATÓRIO DE DEBUG (FREQUÊNCIA - PRODUÇÃO)")
        print("="*80)
        success_count = len(self.freq_trends_processed)
        print(f"\n✅ GRUPOS PROCESSADOS: {success_count}")
        print(f"   • Total de registros lidos: {self.total_records_read}")
        print(f"\n⚠️  TAGS PULADAS: {len(self.freq_tags_skipped)}")
        print(f"❌ ERROS CRÍTICOS: {len(self.freq_tags_failed)}")
        print("="*80 + "\n")

# ============================================================================
# FUNÇÕES AUXILIARES
# ============================================================================

def setup_argument_parser():
    parser = argparse.ArgumentParser(description="Z-Score Frequência (Produção)")
    parser.add_argument('-d', '--data', dest='end_date', type=str)
    parser.add_argument('--config-name', dest='config_name', type=str)
    parser.add_argument('--window', dest='window_size', type=int)
    parser.add_argument('--multiplier', dest='multiplier', type=float)
    return parser

# MODIFICADO: Engine unificada de produção
def get_main_db_engine():
    load_dotenv()
    try:
        conn_str = (
            f"postgresql://{os.getenv('DB_USERNAME')}:"
            f"{quote_plus(os.getenv('DB_PASSWORD'))}@"
            f"{os.getenv('DB_ADDRESS')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
        )
        return create_engine(conn_str)
    except Exception as e:
        logger.error(f"Erro DB Principal: {e}")
        return None

def create_or_get_config(zscore_db, args):
    if args.config_name and args.window_size and args.multiplier:
        config_data = {
            'config_name': args.config_name,
            'window_size_days': args.window_size,
            'zscore_std_multiplier': args.multiplier,
            'step_size_days': 1,
            'is_active': True
        }
        return zscore_db.create_and_activate_config(config_data)
    else:
        config = zscore_db.get_active_config()
        if not config:
            config_data = {'config_name': 'default', 'window_size_days': 7, 'zscore_std_multiplier': 3.0, 'step_size_days': 1, 'is_active': True}
            return zscore_db.create_and_activate_config(config_data)
        return config

def extract_park_from_machine(machine_name):
    return machine_name.split('-')[0] if '-' in machine_name else 'DEFAULT_PARK'

def extract_trend_name_from_tag(full_tag):
    parts = full_tag.split('_')
    return '_'.join(parts[2:]) if len(parts) >= 3 else full_tag

def check_data_quality(df, tag_name):
    if df.empty: return False, "Vazio"
    if (df['Value'] == 0).all(): return False, "Zero absoluto"
    std_dev = df['Value'].std()
    if pd.isna(std_dev) or std_dev < 1e-12: 
        return False, f"Dados constantes ({df['Value'].iloc[0]:.8f})"
    return True, "OK"

def process_frequency_data(freq_db_queries, tag, machine_name, full_start_str, full_end_str, debug_tracker):
    try:
        df_raw, df_processed = freq_db_queries.carregar_dados_tendencia_especifica(tag, full_start_str, full_end_str)
        if df_processed is None or df_processed.empty: return None
        df_processed['Equipamento'] = machine_name
        df_processed['Value'] = pd.to_numeric(df_processed['Value'], errors='coerce').astype(np.float64)
        df_processed.dropna(subset=['Value'], inplace=True)
        is_valid, reason = check_data_quality(df_processed, tag)
        if not is_valid:
            debug_tracker.log_skipped(tag, reason)
            return None
        return df_processed
    except Exception as e:
        debug_tracker.log_failed(tag, str(e))
        return None

# ============================================================================
# FUNÇÃO PRINCIPAL
# ============================================================================

def run_zscore_calculation(end_date_str: str = None, args=None):
    start_run_time = datetime.now()
    debug_tracker = DebugTracker()

    print("\n" + "="*60)
    print("🚀 Z-SCORE FREQUÊNCIA - AMBIENTE DE PRODUÇÃO") 
    print("="*60)
    
    main_engine = get_main_db_engine()
    zscore_db = ZScoreDatabaseHandler()

    if not main_engine or not zscore_db.conn:
        print("❌ Falha nas conexões de produção. Abortando.")
        return

    config = create_or_get_config(zscore_db, args)
    if not config: return

    data_final_dt = datetime.strptime(end_date_str, "%Y-%m-%d").replace(hour=0, minute=0, second=0) if end_date_str else datetime.now().replace(hour=0, minute=0, second=0)

    window_days = int(config.get('window_size_days', 7))
    window_days_guaranteed = max(window_days, 31) 
    full_start_dt_naive = (data_final_dt + timedelta(days=1)) - timedelta(days=window_days_guaranteed)

    freq_start_str = full_start_dt_naive.strftime('%Y-%m-%d')
    freq_end_str = (data_final_dt + timedelta(days=1)).strftime('%Y-%m-%d')
    
    db_queries = DatabaseQueries(main_engine)
    freq_db_queries = FrequencyDatabaseQueries(main_engine)
    zscore_calculator = ZScoreCalculator()
    
    execution_id = zscore_db.insert_execution_summary(start_run_time, config['id'], schemas='freq', date_filter=data_final_dt.date())

    try:
        zscore_config = {'window_size_days': window_days, 'zscore_std_multiplier': config['zscore_std_multiplier']}
        summary_stats = {"processed_parks": 0, "processed_machines": 0, "processed_freq_trends": 0, "zscore_records_inserted": 0}

        all_freq_trends_df = freq_db_queries.carregar_todas_tendencias_disponiveis()
        if all_freq_trends_df.empty: return

        all_freq_trends_df['Park'] = all_freq_trends_df['Machine'].apply(extract_park_from_machine)
        all_freq_trends_df['TrendName'] = all_freq_trends_df['Tendencia'].apply(extract_trend_name_from_tag)
        
        machines_df = db_queries.carregar_maquinas()
        all_machines = machines_df['Name'].tolist() if not machines_df.empty else []
        parks = {extract_park_from_machine(m): [] for m in all_machines}
        for m in all_machines: parks[extract_park_from_machine(m)].append(m)

        for park_name, machines_in_park in tqdm(parks.items(), desc="🌀 Parques Freq"):
            park_freq_tags = all_freq_trends_df[all_freq_trends_df['Park'] == park_name]
            if park_freq_tags.empty: continue
                
            for freq_trend_name in park_freq_tags['TrendName'].unique():
                summary_stats["processed_freq_trends"] += 1
                tags_to_process = park_freq_tags[park_freq_tags['TrendName'] == freq_trend_name]
                sensor_name_from_signal = tags_to_process['SignalName'].iloc[0] if not tags_to_process.empty else 'UNKNOWN'
                
                all_machines_freq_data = [process_frequency_data(freq_db_queries, row['Tendencia'], row['Machine'], freq_start_str, freq_end_str, debug_tracker) for _, row in tags_to_process.iterrows() if row['Machine'] in machines_in_park]
                all_machines_freq_data = [d for d in all_machines_freq_data if d is not None]

                if not all_machines_freq_data: continue
                calculation_df = pd.concat(all_machines_freq_data, ignore_index=True)

                zscore_result_df = zscore_calculator.calculate_comparative_zscore(calculation_df, data_final_dt, zscore_config)

                if not zscore_result_df.empty:
                    zscore_result_df['execution_id'] = execution_id
                    zscore_result_df['park_name'] = park_name
                    zscore_result_df['sensor_name'] = sensor_name_from_signal
                    zscore_result_df['trend_name'] = freq_trend_name

                    inserted_count = zscore_db.insert_zscore_results_directly(zscore_result_df, freq_trend_name)
                    summary_stats["zscore_records_inserted"] += inserted_count
                    debug_tracker.log_success(freq_trend_name, len(calculation_df))

        zscore_db.update_execution_summary(execution_id, {
            'end_time': datetime.now(), 'execution_time_seconds': (datetime.now() - start_run_time).total_seconds(),
            'status': 'Completed', 'processed_parks': len(parks), 'processed_machines': len(all_machines),
            'processed_freq_trends': summary_stats["processed_freq_trends"], 'zscore_records_inserted': summary_stats["zscore_records_inserted"]
        })
    
    except Exception as e:
        zscore_db.update_execution_summary(execution_id, {'status': 'Failed', 'error_log': str(e)})
        logger.error(f"❌ ERRO FATAL: {e}", exc_info=True)

    finally:
        debug_tracker.print_summary()
        zscore_db.close()

if __name__ == "__main__":
    arg_parser = setup_argument_parser()
    args = arg_parser.parse_args()
    run_zscore_calculation(end_date_str=args.end_date, args=args)