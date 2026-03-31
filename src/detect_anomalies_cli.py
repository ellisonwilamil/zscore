import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import date, datetime, timedelta
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, exc
from tqdm import tqdm
from urllib.parse import quote_plus
from utils.MathMetrics import MathMetrics
from utils.DatabaseQueries import DatabaseQueries
from utils.FuzzyIgasCalculator import FuzzyIgasCalculator
from utils.DbHandler import AnomalyDatabaseHandler
from utils.InertiaManager import InertiaManager
from utils.TimeUtils import standardize_to_utc, UTC_TZ, SAO_PAULO_TZ

# Bases de IGAS utilizadas no cálculo
BASES_IGAS = ['Peak_g', 'RMS_g', 'DEF', 'FC'] 

# Configuração básica de log para registrar eventos e erros
logging.basicConfig(
    filename='anomaly_detection.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)
 
# Classe para converter tipos de dados NumPy para JSON
class NumpyJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.integer): return int(obj)
        if isinstance(obj, np.floating): return float(obj)
        if isinstance(obj, np.ndarray): return obj.tolist()
        if pd.isna(obj): return None
        if obj == np.inf: return "Infinity"
        if obj == -np.inf: return "-Infinity"
        return super().default(obj)
 
# Configura o parser de argumentos de linha de comando
def _setup_argument_parser():
    parser = argparse.ArgumentParser(description="Detecção de anomalias e cálculo do IGAS.")
    parser.add_argument('--maquina', help='Nome da máquina (opcional)')
    parser.add_argument('--sensor', help='Nome do sensor (opcional)')
    parser.add_argument('--data', help='Data final (YYYY-MM-DD, opcional)')
    parser.add_argument('--output', help='Nome do arquivo de saída JSON (opcional)')
    return parser

def execute_with_retry(func, *args, max_tentativas=5, intervalo=10, **kwargs):
    """
    Tenta executar uma função de banco de dados 'max_tentativas' vezes.
    intervalo: tempo em segundos entre as tentativas.
    """
    for tentativa in range(1, max_tentativas + 1):
        try:
            return func(*args, **kwargs)
        except (exc.OperationalError, exc.InterfaceError) as e:
            logging.warning(f"⚠️ Tentativa {tentativa}/{max_tentativas} falhou: Erro de conexão. Retentando em {intervalo}s...")
            if tentativa == max_tentativas:
                logging.error("❌ Limite de tentativas de conexão atingido.")
                raise e 
            time.sleep(intervalo)
 
# MODIFICADO: Engine de conexão agora utiliza variáveis unificadas de produção
def _create_db_engine():
    load_dotenv()
    try:
        conn_str = (
            f"postgresql://{os.getenv('DB_USERNAME')}:{quote_plus(os.getenv('DB_PASSWORD'))}@"
            f"{os.getenv('DB_ADDRESS')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
        )
        return create_engine(
            conn_str,
            pool_pre_ping=True, 
            pool_recycle=60, 
            pool_size=10, 
            max_overflow=20, 
            connect_args={'connect_timeout': 20} 
        )
    except Exception as e:
        logging.error(f"Erro ao criar engine de conexão com banco de origem: {e}")
        print(f"❌ Erro de conexão (banco de origem): {e}", file=sys.stderr)
        sys.exit(1)

# Normaliza fuso 
def normalize_dataframe_timezone(df, target_tz="UTC"):
    """
    Garante que o DataFrame tenha timezone aware em UTC, 
    tratando a origem America/Sao_Paulo se for naive.
    """
    if df.empty:
        return df
    
    df['DateTime'] = pd.to_datetime(df['DateTime'])
    
    if df['DateTime'].dt.tz is None:
        df['DateTime'] = df['DateTime'].dt.tz_localize('America/Sao_Paulo').dt.tz_convert('UTC')
    else:
        df['DateTime'] = df['DateTime'].dt.tz_convert('UTC')
        
    return df.sort_values("DateTime")

# Processa uma única tendência para detecção de anomalias e cálculo de métricas
def _process_single_tendencia(math_analyzer, df_anual_sensor, tendencia, date_params):
    try:
        if df_anual_sensor is None or df_anual_sensor.empty:
            return None, None
 
        df_t = df_anual_sensor[df_anual_sensor['Tendencia'] == tendencia].copy()
 
        if df_t.empty:
            return None, None
         
        raw_values = df_t['Value'].values
        cleaned_values = math_analyzer.interpolate_outliers(raw_values)
        df_t['Value'] = cleaned_values    
 
        sec = math_analyzer.calculate_secondary_axis_metrics(
            base_df_for_year=df_t,
            selected_tendencia_name=tendencia,
            filter_start_datetime=date_params['filter_start_dt'],
            filter_end_datetime=date_params['filter_end_dt'],
            threshold_value=0.0,
            treatment_method="Média"
        )
 
        if "error" in sec and sec["error"]:
            logging.warning(f"Erro em MathMetrics para tendência {tendencia}: {sec['error']}")
            return None, None
 
        anomalies_df = sec.get('anomalies_df')
        df_angulos = sec.get("df_angulos")
 
        if anomalies_df is None or anomalies_df.empty:
            return None, df_angulos
 
        results = {}
        for _, row in anomalies_df.iterrows():
            var_val = row['Var']
            thr_val = row['Adaptive_Threshold']
            with np.errstate(divide='ignore', invalid='ignore'):
                if thr_val and var_val > thr_val:
                    excesso = ((var_val / thr_val) - 1) * 100
                else:
                    excesso = 0.0
 
            dt_utc = row['DateTime']
            results[dt_utc.isoformat()] = {
                "Var": var_val,
                "Threshold": thr_val,
                "Diff": row['Diff'],
                "ExcessoPercentual": excesso
            }
        return results, df_angulos
 
    except Exception as e:
        logging.error(f"Erro ao processar tendência {tendencia}: {e}")
        return None, None
 
# Função principal do script
def main():
    start_time = datetime.now(UTC_TZ)
    print("="*50)
    print("⚙️  INICIANDO DETECÇÃO DE ANOMALIAS (PRODUÇÃO)")
    print("="*50)
 
    args = _setup_argument_parser().parse_args()
    engine = _create_db_engine()
    db = DatabaseQueries(engine)
    math_analyzer = MathMetrics()
    fuzzy_calculator = FuzzyIgasCalculator()
    
    # O handler já foi refatorado para apontar internamente para "AnalyticsAnomalies"
    anomaly_db_handler = AnomalyDatabaseHandler()
 
    if not anomaly_db_handler.conn:
        print("❌ Não foi possível conectar ao banco de dados de anomalias. O script será encerrado.", file=sys.stderr)
        sys.exit(1)
 
    print("✅ Módulos e conexões com bancos inicializados.")
 
    if args.data:
        try:
            data_final_dt = datetime.strptime(args.data, "%Y-%m-%d")
        except ValueError:
            print(f"❌ Formato de data inválido: {args.data}. Use YYYY-MM-DD.", file=sys.stderr)
            sys.exit(1)
    else:
        data_final_dt = datetime.combine(date.today(), datetime.min.time())
    print(f"🗓️  Data final da análise: {data_final_dt.strftime('%Y-%m-%d')}")

    start_search_date, _ = InertiaManager.get_search_range(data_final_dt)
 
    filter_end_dt = UTC_TZ.localize(datetime.combine(data_final_dt, datetime.max.time()))
    filter_start_dt = UTC_TZ.localize(datetime.combine(data_final_dt - timedelta(days=29), datetime.min.time()))
 
    date_params = {
        'filter_end_dt': filter_end_dt,
        'filter_start_dt': filter_start_dt,
        'data_final_str': data_final_dt.strftime('%Y.%m.%d'),
        'full_start_str': start_search_date.strftime('%Y.%m.%d'),
        'full_end_str': data_final_dt.strftime('%Y.%m.%d')
    }
 
    initial_summary_data = {
        "start_time": start_time,
        "end_time": None,
        "status": "Running",
        "execution_time_seconds": None,
        "total_anomalies_detected": 0,
        "total_anomalies_inserted": 0,
        "total_duplicates": 0,
        "total_errors": 0,
        "max_value": None,
        "machine_filter": args.maquina,
        "sensor_filter": args.sensor,
        "date_filter": data_final_dt.date()
    }
    
    script_execution_id = anomaly_db_handler.insert_execution_summary(initial_summary_data)

    if script_execution_id is None:
        print("❌ Falha ao inserir o sumário de execução inicial. O script será encerrado.", file=sys.stderr)
        anomaly_db_handler.close()
        sys.exit(1)
    print(f"📝 ID da execução: {script_execution_id}")

    maquinas = [args.maquina] if args.maquina else [m for m in db.carregar_maquinas()['Name'].tolist() if m != 'REF']
    print(f"🔩 Total de máquinas para análise: {len(maquinas)}")

    saida_final_json = {}
    total_anomalias_detectadas = 0
    total_anomalias_inseridas = 0
    total_igas_calculado = 0
   
    padroes_igas = {'Peak_g': re.compile(r'Peak_g'), 'RMS_g': re.compile(r'RMS_g'), 'FC': re.compile(r'FC'), 'DEF': re.compile(r'DEF')}
    tendencias_necessarias_igas = set(padroes_igas.keys())
        
    try:
        for maquina in maquinas:
            print(f"\n[MÁQUINA] -> {maquina}")

            sensores_df = execute_with_retry(
                db.carregar_sensores, 
                maquina, 
                max_tentativas=15, 
                intervalo=30
            )
            
            sensores = [args.sensor] if args.sensor else sensores_df['sensor_name'].tolist()
    
            with tqdm(total=len(sensores), desc="[SENSORES]", ncols=100, unit="sensor", leave=True) as pbar:
                for sensor in sensores:
                    pbar.set_postfix_str(f"Analisando {sensor}...")
    
                    try:
                        _, df_anual_sensor = execute_with_retry(
                            db.carregar_dados_tendencia, 
                            maquina, 
                            sensor, 
                            date_params['full_start_str'], 
                            date_params['full_end_str'],
                            max_tentativas=15,
                            intervalo=30
                        ) 

                        if df_anual_sensor is None or df_anual_sensor.empty:
                            pbar.update(1)
                            continue
                        
                        df_anual_sensor = standardize_to_utc(df_anual_sensor)
                        data_final_dt_utc = pd.to_datetime(data_final_dt).tz_localize(SAO_PAULO_TZ).tz_convert(UTC_TZ)

                        inertia_info = InertiaManager.evaluate_inertia(df_anual_sensor, data_final_dt_utc)
                        
                        if not inertia_info["valid"]:
                            logging.warning(f"Sensor {maquina}::{sensor} ignorado: {inertia_info['status']}")
                            pbar.update(1)
                            continue
                        
                        logging.info(f"Sensor {maquina}::{sensor} validado com {inertia_info['status']}")
    
                        if not pd.api.types.is_datetime64_any_dtype(df_anual_sensor['DateTime']):
                            df_anual_sensor['DateTime'] = pd.to_datetime(df_anual_sensor['DateTime'])
    
                        df_anual_sensor['DateTime'] = df_anual_sensor['DateTime'].dt.tz_convert(UTC_TZ)
                        df_anual_sensor['Value'] = pd.to_numeric(df_anual_sensor['Value'], errors='coerce')
    
                    except Exception as e:
                        logging.error(f"Erro ao carregar ou preparar dados para {maquina}::{sensor}: {e}")
                        pbar.update(1)
                        continue
    
                    tendencias_unicas = df_anual_sensor['Tendencia'].unique()
                    dados_para_igas = {}
                    anomalias_por_timestamp = {}
                    tendencias_encontradas_para_igas = set()
    
                    for tendencia in tendencias_unicas:
                        if "RPM" in tendencia:
                            logging.info(f"Ignorando tendência '{tendencia}' para {maquina}::{sensor}.")
                            continue
    
                        logging.info(f"Processando {maquina}::{sensor}::{tendencia}")
                        resultados, df_angulos = _process_single_tendencia(math_analyzer, df_anual_sensor, tendencia, date_params)
    
                        if resultados:
                            total_anomalias_detectadas += len(resultados)
                            chave_json = f"{maquina}::{sensor}::{tendencia}"
                            saida_final_json[chave_json] = resultados
    
                            for dt_str, valores in resultados.items():
                                anomaly_datetime = datetime.fromisoformat(dt_str)
                                success = anomaly_db_handler.insert_anomaly(
                                    script_execution_id=script_execution_id,
                                    machine_name=maquina, 
                                    sensor_name=sensor, 
                                    trend_name=tendencia,
                                    anomaly_datetime=anomaly_datetime, 
                                    var_value=valores["Var"],
                                    adaptive_threshold=valores["Threshold"], 
                                    diff_value=valores["Diff"],
                                    excess_percent=valores["ExcessoPercentual"], 
                                    igas_value=None
                                )
                                if success: total_anomalias_inseridas += 1
    
                                if dt_str not in anomalias_por_timestamp: anomalias_por_timestamp[dt_str] = []
                                anomalias_por_timestamp[dt_str].append({"tendencia": tendencia})
    
                        for tipo, padrao in padroes_igas.items():                        
                            if padrao.search(tendencia) and "1k_HP" not in tendencia:
                                if (df_angulos is not None and not df_angulos.empty and
                                    'Var' in df_angulos.columns and df_angulos['Var'].nunique() > 1):
                                    
                                    tendencias_encontradas_para_igas.add(tipo)
                                    dados_para_igas[tipo] = df_angulos
                                    logging.info(f"Dados angulares para IGAS ({tipo}) coletados em {tendencia}")
                                else:
                                    logging.warning(f"Dados angulares para IGAS ({tipo}) em {tendencia} são inválidos.")
                                break 
                            if "1k_HP" in tendencia:
                                continue
    
                    if tendencias_encontradas_para_igas.issuperset(tendencias_necessarias_igas):
                        pbar.set_postfix_str(f"Calculando IGAS para {sensor}...")
                        try:
                            df_igas = fuzzy_calculator.calculate(dados_para_igas)
                            if not df_igas.empty:
                                total_igas_calculado += len(df_igas)
                                for _, igas_row in df_igas.iterrows():
                                    if pd.notna(igas_row['indice_tsk']):
                                        igas_value = float(igas_row['indice_tsk'])
                                        ts_str = igas_row['DateTime'].isoformat()
    
                                        if ts_str in anomalias_por_timestamp:
                                            for anomalia_info in anomalias_por_timestamp[ts_str]:
                                                tendencia_anomalia = anomalia_info['tendencia']
                                                anomaly_db_handler.insert_anomaly(
                                                    script_execution_id=script_execution_id,
                                                    machine_name=maquina, 
                                                    sensor_name=sensor, 
                                                    trend_name=tendencia_anomalia,
                                                    anomaly_datetime=datetime.fromisoformat(ts_str), 
                                                    igas_value=igas_value
                                                )
                                                chave_anomalia_json = f"{maquina}::{sensor}::{tendencia_anomalia}"
                                                if chave_anomalia_json in saida_final_json and ts_str in saida_final_json[chave_anomalia_json]:
                                                    saida_final_json[chave_anomalia_json][ts_str]["IGAS"] = igas_value
                                    else:
                                        logging.warning(f"Valor de IGAS nulo encontrado para {maquina}::{sensor}.")
                        except Exception as e:
                            logging.error(f"Erro no cálculo ou associação do IGAS para {maquina}::{sensor}: {e}")
    
                    pbar.update(1)
            status_final = "Completed"
    except Exception as e:
        logging.critical(f"💥 Erro fatal irrecuperável: {e}")
        status_final = "Failed"
        raise 
           
    finally:
        end_time = datetime.now(UTC_TZ)
        execution_time = (end_time - start_time).total_seconds()
    
        updated_summary_data = {
            "status": status_final,
            "end_time": end_time,
            "execution_time_seconds": execution_time,
            "total_anomalies_detected": total_anomalias_detectadas,
            "total_anomalies_inserted": total_anomalias_inseridas,
            "total_duplicates": (total_anomalias_detectadas - total_anomalias_inseridas)
        }
 
    update_success = anomaly_db_handler.update_execution_summary(script_execution_id, updated_summary_data)
    if update_success:
        print("✅ Sumário de execução atualizado com sucesso.")
    else:
        print("❌ Falha ao atualizar o sumário de execução.")
 
    anomaly_db_handler.close()
 
    print("\n" + "="*50)
    print("📊 RESUMO FINAL DA EXECUÇÃO")
    print("="*50)
    print(f"  📈 Total de anomalias detectadas: {total_anomalias_detectadas}")
    print(f"  💾 Total de anomalias inseridas/atualizadas: {total_anomalias_inseridas}")
    print(f"  🧠 Total de registros IGAS calculados: {total_igas_calculado}")
 
    output_file = args.output or f"anomalies_detection_{data_final_dt.date()}.json"
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(saida_final_json, f, indent=2, ensure_ascii=False, cls=NumpyJSONEncoder)
        print(f"  📄 Resultados JSON salvos em: {output_file}")
    except Exception as e:
        print(f"  ❌ Erro ao salvar JSON: {e}")
    print("="*50)
    print("✅ Execução concluída.")
 
if __name__ == '__main__':
    main()