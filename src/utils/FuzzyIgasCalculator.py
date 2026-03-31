import pandas as pd
import numpy as np
import skfuzzy as fuzz
from skfuzzy import control as ctrl
import logging

class FuzzyIgasCalculator:
    def __init__(self):
        self._setup_fuzzy_system()
    
    def _setup_fuzzy_system(self):
        # Variáveis de entrada
        self.peak = ctrl.Antecedent(np.arange(0, 101, 1), 'Peak_g')
        self.rms = ctrl.Antecedent(np.arange(0, 101, 1), 'RMS_g')
        self.defect = ctrl.Antecedent(np.arange(0, 101, 1), 'DEF')
        self.freq_center = ctrl.Antecedent(np.arange(0, 101, 1), 'FC')
        
        # Variável de saída
        self.igas = ctrl.Consequent(np.arange(0, 101, 1), 'IGAS')
        
        # Funções de pertinência
        for var in [self.peak, self.rms, self.defect, self.freq_center]:
            var['baixo'] = fuzz.trimf(var.universe, [0, 0, 50])
            var['medio'] = fuzz.trimf(var.universe, [30, 50, 70])
            var['alto'] = fuzz.trimf(var.universe, [50, 100, 100])
        
        self.igas['baixo'] = fuzz.trimf(self.igas.universe, [0, 0, 50])
        self.igas['medio'] = fuzz.trimf(self.igas.universe, [30, 50, 70])
        self.igas['alto'] = fuzz.trimf(self.igas.universe, [50, 100, 100])
        
        # >>> CORREÇÃO FINAL: REGRAS FUZZY MAIS ABRANGENTES <<<
        # Alteramos os operadores 'E' (&) para 'OU' (|) nas regras de criticidade.
        # Se QUALQUER indicador estiver alto, a saída tende para 'alto'.
        # Isso garante que sempre haverá uma regra ativa, resolvendo o KeyError.
        rules = [
            ctrl.Rule(self.peak['alto'] | self.rms['alto'] | self.defect['alto'] | self.freq_center['alto'], self.igas['alto']),
            ctrl.Rule(self.peak['medio'] | self.rms['medio'] | self.defect['medio'] | self.freq_center['medio'], self.igas['medio']),
            ctrl.Rule(self.peak['baixo'] | self.rms['baixo'] | self.defect['baixo'] | self.freq_center['baixo'], self.igas['baixo'])
        ]
        
        # Sistema de controle
        self.igas_ctrl = ctrl.ControlSystem(rules)
        # Define o método de defuzzificação
        self.igas.defuzzify_method = 'centroid'
        self.igas_sim = ctrl.ControlSystemSimulation(self.igas_ctrl)

    def calculate(self, anom_results_dict: dict) -> pd.DataFrame:
        required_keys = ['Peak_g', 'RMS_g', 'DEF', 'FC']
        missing_keys = [key for key in required_keys if key not in anom_results_dict]
        
        if missing_keys:
            logging.error(f"Faltando tendências para cálculo do IGAS: {missing_keys}")
            return pd.DataFrame()
        
        try:
            df_combined = pd.DataFrame()
            
            for key in required_keys:
                df_temp = anom_results_dict[key][['DateTime', 'Var']].copy()
                df_temp.rename(columns={'Var': key}, inplace=True)
                
                if df_combined.empty:
                    df_combined = df_temp
                else:
                    df_combined = pd.merge_asof(df_combined.sort_values('DateTime'), 
                                              df_temp.sort_values('DateTime'), 
                                              on='DateTime', 
                                              direction='nearest')
            
            df_combined.dropna(inplace=True)

            if df_combined.empty:
                logging.warning("Após o merge e limpeza de NaNs, nenhum dado completo restou para o cálculo do IGAS.")
                return pd.DataFrame()

            for col in required_keys:
                col_min = df_combined[col].min()
                col_max = df_combined[col].max()
                
                if col_max > col_min:
                    df_combined[col] = (df_combined[col] - col_min) / (col_max - col_min) * 100
                else:
                    df_combined[col] = 0
            
            igas_values = []
            for _, row in df_combined.iterrows():
                try:
                    self.igas_sim.input['Peak_g'] = row['Peak_g']
                    self.igas_sim.input['RMS_g'] = row['RMS_g']
                    self.igas_sim.input['DEF'] = row['DEF']
                    self.igas_sim.input['FC'] = row['FC']
                    self.igas_sim.compute()
                    igas_values.append(self.igas_sim.output['IGAS'])
                except Exception as e:
                    logging.error(f"Erro no cálculo fuzzy para a linha {row.to_dict()}: {e}")
                    igas_values.append(None)
            
            df_combined['indice_tsk'] = igas_values
            return df_combined[['DateTime', 'indice_tsk']].dropna()
            
        except Exception as e:
            logging.error(f"Erro ao calcular IGAS: {e}")
            return pd.DataFrame()