import pandas as pd
import numpy as np
from scipy.interpolate import interp1d
from scipy.signal import find_peaks
from scipy.stats import linregress
from statsmodels.tsa.seasonal import seasonal_decompose
import streamlit as st 
from utils.config import WINDOW_SIZE, NUM_STD_DEV, MIN_PEAK_PERCENTAGE, SIGMAS
import pytz


class MathMetrics:
    def __init__(self):
        """
        Initializes the MathMetrics class.
        """
        self.fuzzy_calculator = None

    
    def interpolate_outliers(self, arr):
        """
        Identifica e substitui outliers que excedem SIGMAS desvios padrão (sigma) da média,
        utilizando interpolação linear entre os pontos válidos adjacentes.
        """
        # Garante que o array de entrada seja um array numpy de tipo float
        arr = np.array(arr, dtype=float)
        
        # Se o array tiver menos de 3 pontos, não é possível calcular desvio padrão ou interpolar
        if len(arr) < 3:
            return arr

        # Calcula a média e o desvio padrão (sigma) dos dados
        mean = np.mean(arr)
        std_dev = np.std(arr)

        # Define os limites superior e inferior (3-sigma)
        upper_bound = mean + SIGMAS * std_dev
        lower_bound = mean - SIGMAS * std_dev

        # Cria uma cópia do array para modificação
        new_arr = arr.copy()

        # Encontra os índices dos valores que estão DENTRO dos limites (não são outliers)
        valid_indices = np.where((arr >= lower_bound) & (arr <= upper_bound))[0]

        # Se não houver pontos válidos ou apenas um, não é possível interpolar.
        if len(valid_indices) < 2:
            return arr

        # Trata outliers no início do array
        first_valid_idx = valid_indices[0]
        if first_valid_idx > 0:
            new_arr[0:first_valid_idx] = arr[first_valid_idx]

        # Itera entre os pontos válidos para interpolar as sequências de outliers
        for i in range(len(valid_indices) - 1):
            start_idx = valid_indices[i]
            end_idx = valid_indices[i+1]
            
            if end_idx - start_idx > 1:
                start_val = arr[start_idx]
                end_val = arr[end_idx]
                
                fractions = (np.arange(start_idx + 1, end_idx) - start_idx) / (end_idx - start_idx)
                new_arr[start_idx + 1 : end_idx] = start_val + fractions * (end_val - start_val)

        # Trata outliers no final do array
        last_valid_idx = valid_indices[-1]
        if last_valid_idx < len(arr) - 1:
            new_arr[last_valid_idx+1:] = arr[last_valid_idx]
        
        return new_arr

    def _calcular_angulo_rolling(self, df, coluna='Variancia_Acumulada', window=10):
        """Calcula o ângulo de uma série usando uma janela deslizante (rolling)."""
        angulos = []
        for i in range(len(df)):
            if i < window:
                angulos.append(np.nan)
            else:
                y = df[coluna].iloc[i-window:i]
                x = np.arange(window)
                if y.dropna().shape[0] < 2:
                    angulos.append(np.nan)
                    continue
                slope, _, _, _, _ = linregress(x, y)
                angulo = np.degrees(np.arctan(slope))
                angulos.append(angulo)
        return angulos

    def _calcular_covariancia_rolling(self, df, coluna='Variancia_Acumulada', window=10):
        """Calcula a covariância entre o tempo e o valor em uma janela deslizante."""
        covs = []
        for i in range(len(df)):
            if i < window:
                covs.append(np.nan)
            else:
                y = df[coluna].iloc[i-window:i]
                x = np.arange(window)
                if y.dropna().shape[0] < 2:
                    covs.append(np.nan)
                    continue
                cov = np.cov(x, y)[0, 1]
                covs.append(cov)
        return covs

    def replace_below_threshold_strategy(self, arr, threshold, method):
        """
        Replaces values below the threshold using the selected strategy.
        """
        arr = np.array(arr, dtype=float)
        
        if method == "Média anterior":
            new_arr = []
            sum_valid = 0
            count_valid = 0
            for val in arr:
                if val <= threshold:
                    new_val = sum_valid / count_valid if count_valid > 0 else 0
                    new_arr.append(new_val)
                else:
                    new_arr.append(val)
                    sum_valid += val
                    count_valid += 1
            return np.array(new_arr)    
        
        elif method == "Reta":
            new_arr = arr.copy()
            valid_indices = np.where(arr > threshold)[0]
            
            if len(valid_indices) < 2:
                return new_arr

            if valid_indices[0] > 0:
                new_arr[0:valid_indices[0]] = arr[valid_indices[0]]

            for i in range(len(valid_indices) - 1):
                start_idx = valid_indices[i]
                end_idx = valid_indices[i+1]
                
                if end_idx - start_idx > 1:
                    start_val = arr[start_idx]
                    end_val = arr[end_idx]
                    fractions = (np.arange(start_idx + 1, end_idx) - start_idx) / (end_idx - start_idx)
                    new_arr[start_idx + 1 : end_idx] = start_val + fractions * (end_val - start_val)

            if valid_indices[-1] < len(arr) - 1:
                 new_arr[valid_indices[-1]+1:] = arr[valid_indices[-1]]
            
            return new_arr
        else:
            return arr

    def calculate_primary_trend_metrics(self, y_values, x_timestamps, x_dates,
                                        rolling_periods=4, peak_distance=10,
                                        percentual_minimo_picos=MIN_PEAK_PERCENTAGE):
        """
        Calculates primary metrics for trend analysis.
        """
        metrics = {}
        metrics['y_processed'] = y_values

        metrics['media_movel'] = pd.Series(y_values).rolling(window=rolling_periods, min_periods=1).mean()
        
        # Garante que há dados suficientes para a regressão
        if len(x_timestamps) > 1 and len(y_values) > 1:
            slope, intercept, r_value, p_value, std_err = linregress(x_timestamps, y_values)
            metrics['tendencia_line'] = intercept + slope * x_timestamps
            metrics['slope'] = slope
            metrics['intercept'] = intercept
        else:
            metrics['tendencia_line'] = np.full_like(y_values, np.nan)
            metrics['slope'] = np.nan
            metrics['intercept'] = np.nan

        metrics['mediana'] = np.median(y_values)
        metrics['desvio_padrao'] = np.std(y_values)
        
        peaks_upper_indices, _ = find_peaks(y_values, distance=peak_distance)
        unique_upper_indices = np.unique(np.concatenate([[0], peaks_upper_indices, [len(y_values)-1]]))
        if len(unique_upper_indices) >= 2 and len(x_timestamps) > 1:
            sorted_indices_upper = np.sort(unique_upper_indices)
            f_upper = interp1d(x_timestamps[sorted_indices_upper], y_values[sorted_indices_upper], 
                               kind='cubic', fill_value="extrapolate", bounds_error=False)
            x_new_interp = np.linspace(x_timestamps.min(), x_timestamps.max(), 500)
            metrics['x_envelope_new_dates'] = pd.to_datetime(x_new_interp, unit='s')
            metrics['y_upper_envelope'] = f_upper(x_new_interp)
        else:
            if len(x_timestamps) > 0:
                metrics['x_envelope_new_dates'] = pd.to_datetime(np.linspace(x_timestamps.min(), x_timestamps.max(), 500), unit='s')
            else:
                metrics['x_envelope_new_dates'] = pd.to_datetime([], unit='s')
            metrics['y_upper_envelope'] = np.full(500, np.nan)

        peaks_lower_indices, _ = find_peaks(-y_values, distance=peak_distance)
        unique_lower_indices = np.unique(np.concatenate([[0], peaks_lower_indices, [len(y_values)-1]]))
        if len(unique_lower_indices) >= 2 and 'x_envelope_new_dates' in metrics and not metrics['x_envelope_new_dates'].empty:
            sorted_indices_lower = np.sort(unique_lower_indices)
            f_lower = interp1d(x_timestamps[sorted_indices_lower], y_values[sorted_indices_lower], 
                               kind='cubic', fill_value="extrapolate", bounds_error=False)
            metrics['y_lower_envelope'] = f_lower(x_new_interp)
        else:
            metrics['y_lower_envelope'] = np.full(500, np.nan)

        y_ref_picos = metrics['mediana'] + 3 * metrics['desvio_padrao']
        fator_minimo_picos = 1 + (percentual_minimo_picos / 100.0)
        peak_indices, _ = find_peaks(y_values, distance=peak_distance)
        
        metrics['filtered_peak_indices'] = [p for p in peak_indices if y_values[p] > y_ref_picos * fator_minimo_picos]
        metrics['peak_texts'] = [f'+{((y_values[p]-y_ref_picos)/y_ref_picos*100):.1f}%' if y_ref_picos > 0 else '+inf%' for p in metrics['filtered_peak_indices']]
        
        return metrics

    def calculate_secondary_axis_metrics(self,
                                         base_df_for_year,
                                         selected_tendencia_name,
                                         filter_start_datetime,
                                         filter_end_datetime,
                                         threshold_value,
                                         treatment_method,
                                         decomposition_period=144,
                                         adaptive_threshold_window=WINDOW_SIZE,
                                         adaptive_threshold_k=NUM_STD_DEV):
        """
        Calculates metrics for the secondary y-axis.
        """
        results = {}
        

        if base_df_for_year is None or base_df_for_year.empty:
            results['error'] = "Base DataFrame is empty."
            results['df_angulos'] = pd.DataFrame()
            results['trend_full_for_plot'] = pd.Series(dtype=float)
            results['angles_evolution'] = pd.Series(dtype=float)
            results['anomalies_df'] = pd.DataFrame()
            return results

        orig_df_for_decomp = (
            base_df_for_year[base_df_for_year['Tendencia'] == selected_tendencia_name]
            .sort_values('DateTime')
            .copy()
        )
        
        earliest_data_point = orig_df_for_decomp['DateTime'].min()
        
        decomp_start_date = max(
            earliest_data_point,
            filter_start_datetime - pd.Timedelta(days=365)
        )

        df_ext = orig_df_for_decomp[
            (orig_df_for_decomp["DateTime"] >= decomp_start_date) &
            (orig_df_for_decomp["DateTime"] <= filter_end_datetime)
        ].copy()

        if df_ext.empty or len(df_ext) < decomposition_period * 2:
            results['error'] = "Not enough data for seasonal decomposition or secondary axis metrics."
            results['df_angulos'] = pd.DataFrame()
            results['trend_full_for_plot'] = pd.Series(dtype=float)
            results['angles_evolution'] = pd.Series(dtype=float)
            results['anomalies_df'] = pd.DataFrame()
            return results

        y_ext = self.replace_below_threshold_strategy(
            df_ext['Value'].values, threshold_value, treatment_method
        )
        df_trend_for_decomp = pd.DataFrame({'DateTime': df_ext['DateTime'], 'Value': y_ext})
        df_trend_for_decomp.set_index('DateTime', inplace=True)

        try:
            if len(df_trend_for_decomp['Value']) < decomposition_period:
                 raise ValueError(f"Period ({decomposition_period}) must be less than the number of observations ({len(df_trend_for_decomp['Value'])}).")
            decomp = seasonal_decompose(df_trend_for_decomp['Value'], model='additive', period=decomposition_period, extrapolate_trend='freq')
            trend_full = decomp.trend.bfill().ffill()
        except Exception as e:
            trend_full = df_trend_for_decomp['Value'].rolling(window=decomposition_period, center=True, min_periods=1).mean().bfill().ffill()
            results['warning_decomposition'] = f"Seasonal decomposition failed: {e}. Using rolling mean for trend."
        
        results['trend_full_for_plot'] = trend_full

        angle_calc_results = []
        for i in range(0, len(trend_full), decomposition_period):
            bloco = trend_full.iloc[i : i + decomposition_period]
            if not bloco.empty and len(bloco) > 1:
                x_bloco = np.arange(len(bloco))
                if np.any(~np.isfinite(bloco.values)): continue 
                slope_bloco, _, _, _, _ = linregress(x_bloco, bloco.values)
                angle_calc_results.append({'DateTime': bloco.index[-1], 'Angle': np.degrees(np.arctan(slope_bloco))})
        
        df_angulos = pd.DataFrame(angle_calc_results)

        if not df_angulos.empty:
            df_angulos['Var'] = df_angulos['Angle'].expanding().var().fillna(0)
            df_angulos['Soma'] = df_angulos['Angle'].cumsum()
            df_angulos['Angulo_Acumulado'] = self._calcular_angulo_rolling(df_angulos, coluna='Var', window=10)
            df_angulos['Covariancia_Acumulada'] = self._calcular_covariancia_rolling(df_angulos, coluna='Var', window=10)

            df_angulos = df_angulos[
                (df_angulos['DateTime'] >= filter_start_datetime) & 
                (df_angulos['DateTime'] <= filter_end_datetime)
            ].copy()
            results['df_angulos'] = df_angulos
        else:
            results['df_angulos'] = pd.DataFrame(columns=['DateTime', 'Angle', 'Var', 'Soma'])

        if not trend_full.empty and len(trend_full) > 1:
            slopes_gradient = np.gradient(trend_full.values)
            angles_evolution_series = pd.Series(np.degrees(np.arctan(slopes_gradient)), index=trend_full.index)
            
            angles_evolution_series = angles_evolution_series[
                (angles_evolution_series.index >= filter_start_datetime) &
                (angles_evolution_series.index <= filter_end_datetime)
            ]
            results['angles_evolution'] = angles_evolution_series
        else:
            results['angles_evolution'] = pd.Series(dtype=float)

        anomalies_df = pd.DataFrame()
        if not results['df_angulos'].empty and 'Var' in results['df_angulos'].columns:
            current_df_angulos = results['df_angulos'].copy()
            actual_window_size = min(adaptive_threshold_window, len(current_df_angulos))
            
            if actual_window_size > 0:
                current_df_angulos['Media_Movel_Var'] = current_df_angulos['Var'].rolling(window=actual_window_size, min_periods=1).mean()
                current_df_angulos['Desvio_Movel_Var'] = current_df_angulos['Var'].rolling(window=actual_window_size, min_periods=1).std().fillna(0)
                current_df_angulos['Adaptive_Threshold'] = current_df_angulos['Media_Movel_Var'] + adaptive_threshold_k * current_df_angulos['Desvio_Movel_Var']
                current_df_angulos['Anomalia'] = current_df_angulos['Var'] > current_df_angulos['Adaptive_Threshold']
                
                current_df_angulos['Angulo_Acumulado'] = self._calcular_angulo_rolling(current_df_angulos, coluna='Var', window=10)
                current_df_angulos['Covariancia_Acumulada'] = self._calcular_covariancia_rolling(current_df_angulos, coluna='Var', window=10)

                anomalies_df = current_df_angulos[current_df_angulos['Anomalia']].copy()
                if not anomalies_df.empty:
                    anomalies_df['Diff'] = anomalies_df['Var'] - anomalies_df['Adaptive_Threshold']
                    anomalies_df['%'] = (anomalies_df['Adaptive_Threshold'] / anomalies_df['Var']).replace([np.inf, -np.inf], 0)
            
            results['df_angulos'] = current_df_angulos

        results['anomalies_df'] = anomalies_df
        return results

    def calculate_igas(self, anom_results_dict: dict) -> pd.DataFrame:
        """
        Calcula o IGAS delegando a tarefa para a classe FuzzyIgasCalculator,
        que é carregada dinamicamente apenas quando este método é chamado.
        """
        if self.fuzzy_calculator is None:
            try:
                # --- CORREÇÃO APLICADA AQUI ---
                from .FuzzyIgasCalculator import FuzzyIgasCalculator
                self.fuzzy_calculator = FuzzyIgasCalculator()
            except ImportError:
                st.error("Componentes de lógica fuzzy (FuzzyIgasCalculator) não encontrados ou dependências faltando (scikit-fuzzy, sklearn).")
                return pd.DataFrame()

        return self.fuzzy_calculator.calculate(anom_results_dict)

    def pivot_modbus_data(self, df_modbus_raw):
        """
        Pivots the Modbus DataFrame.
        """
        if df_modbus_raw is None or df_modbus_raw.empty:
            return pd.DataFrame()
            
        df_modbus = df_modbus_raw.copy()
        df_modbus['DateTime'] = pd.to_datetime(df_modbus['DateTime'])
        df_modbus['Value'] = pd.to_numeric(df_modbus['Value'], errors='coerce')
        
        df_pivot = df_modbus.pivot_table(
            index='DateTime',
            columns='Tendencia',
            values='Value',
            aggfunc='mean'
        ).reset_index().rename_axis(None, axis=1)
        return df_pivot
    
    import numpy as np

