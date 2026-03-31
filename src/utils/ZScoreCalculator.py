import pandas as pd
import numpy as np
from datetime import datetime
import pytz

# Configuração do fuso horário
UTC = pytz.timezone('America/Sao_Paulo')

class ZScoreCalculator:
    """
    Classe dedicada para realizar os cálculos comparativos de Z-Score
    para uma data alvo específica.
    """
    def calculate_comparative_zscore(self, df: pd.DataFrame, target_date: datetime, config: dict) -> pd.DataFrame:
        """
        Calcula o Z-Score comparativo para cada equipamento para uma data alvo,
        usando uma janela de dados que a precede.

        Args:
            df (pd.DataFrame): DataFrame com *todo* o histórico de dados ('DateTime', 'Equipamento', 'Value').
            target_date (datetime): A data de verificação (ex: hoje). O cálculo será salvo para este dia.
            config (dict): Dicionário com os parâmetros ('window_size_days', 'zscore_std_multiplier').

        Returns:
            pd.DataFrame: Um DataFrame em formato "longo" com os resultados para cada equipamento
                          APENAS para a 'target_date'.
        """
        
        expected_cols = [
            'machine_name', 'window_end_date', 'z_score', 'variance', 
            'base_fixa', 'group_mean_base_fixa', 'group_std_base_fixa'
        ]

        if df.empty or 'DateTime' not in df.columns or 'Equipamento' not in df.columns or 'Value' not in df.columns:
            print("      ⚠️  ZScoreCalculator: DataFrame de entrada vazio ou com colunas faltando.")
            return pd.DataFrame(columns=expected_cols)

        df['DateTime'] = pd.to_datetime(df['DateTime'])
        
        # Garantir que a data alvo tenha fuso horário (UTC) para comparação
        if target_date.tzinfo is None:
            # Se a data alvo vier sem fuso (ex: 2025-11-06 00:00:00), localiza ela
            try:
                target_date = UTC.localize(target_date)
            except pytz.exceptions.AmbiguousTimeError:
                target_date = UTC.localize(target_date, is_dst=True) # ou is_dst=False, dependendo da política
            except pytz.exceptions.NonExistentTimeError:
                 target_date = UTC.localize(target_date, is_dst=True) # Trata caso de pular horário

        # Garantir que o DataFrame tenha fuso horário (UTC)
        if df['DateTime'].dt.tz is None:
             df['DateTime'] = df['DateTime'].dt.tz_localize(UTC, ambiguous='NaT', nonexistent='NaT')
        else:
             df['DateTime'] = df['DateTime'].dt.tz_convert(UTC)
        
        # Remover valores NaT/None de DateTime após a conversão, se houver
        df.dropna(subset=['DateTime'], inplace=True)

        window_size = pd.Timedelta(days=config['window_size_days'])
        std_multiplier = config['zscore_std_multiplier']
        
        # Define a janela de cálculo (ex: 7 dias *antes* da data alvo)
        # Normaliza a data alvo para o início do dia (00:00:00)
        window_end_date = pd.Timestamp(target_date).normalize()
        window_start_date = window_end_date - window_size # Ex: 2025-10-30 00:00:00-03:00

        df_sorted = df.sort_values(by='DateTime').set_index('DateTime')
        
        # Filtra o DataFrame *apenas* para a janela de dados relevante
        window_df = df_sorted.loc[window_start_date : window_end_date]

        if window_df.empty:
            print(f"      ⚠️  ZScoreCalculator: Nenhum dado encontrado na janela de {window_start_date} a {window_end_date}.")
            return pd.DataFrame(columns=expected_cols)

        # 1. Calcula estatísticas por equipamento na janela
        stats_per_equip = window_df.groupby('Equipamento')['Value'].agg(['mean', 'std', 'var']).reset_index()
        stats_per_equip = stats_per_equip.rename(columns={'var': 'variance'})
        stats_per_equip = stats_per_equip.dropna(subset=['std', 'mean', 'variance']) # Garante que não há NaNs

        if stats_per_equip.empty or len(stats_per_equip) < 2: # Precisa de pelo menos 2 equipamentos para comparar
            print(f"      ⚠️  ZScoreCalculator: Menos de 2 equipamentos com dados válidos na janela.")
            return pd.DataFrame(columns=expected_cols)

        # 2. Calcula a 'base_fixa' para cada equipamento
        stats_per_equip['base_fixa'] = stats_per_equip['mean'] + (std_multiplier * stats_per_equip['std'])

        # 3. Calcula a média e desvio padrão do grupo de 'base_fixa'
        mean_basefixa_group = stats_per_equip['base_fixa'].mean()
        std_basefixa_group = stats_per_equip['base_fixa'].std()

        # 4. Calcula o Z-Score para cada equipamento
        if std_basefixa_group > 0:
            stats_per_equip['z_score'] = (stats_per_equip['base_fixa'] - mean_basefixa_group) / std_basefixa_group
        else:
            stats_per_equip['z_score'] = 0.0

        # 5. Adiciona informações contextuais e armazena
        # Salva com a data final da janela (que é a data alvo)
        stats_per_equip['window_end_date'] = window_end_date.date() 
        stats_per_equip['group_mean_base_fixa'] = mean_basefixa_group
        stats_per_equip['group_std_base_fixa'] = std_basefixa_group
        
        stats_per_equip = stats_per_equip.rename(columns={'Equipamento': 'machine_name'})

        return stats_per_equip[expected_cols]