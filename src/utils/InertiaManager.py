import pandas as pd
import numpy as np
from datetime import timedelta, datetime
class InertiaManager:
    """
    Centraliza a lógica de 'Inércia de Dados' para detecção de anomalias.
    Garante que o cálculo ocorra com histórico de 1 a 12 meses + 1 mês de análise.
    """
    
    @staticmethod
    def get_search_range(target_date):
        """
        Define o range máximo de busca no banco (aprox. 13 meses retroativos).
        Retorna (data_inicio_busca, data_fim_busca).
        """
        if isinstance(target_date, datetime):
            target_date = target_date.date()
        
        # Busca 395 dias para garantir 12 meses de histórico + 30 dias de janela alvo
        start_search = target_date - timedelta(days=395)
        return start_search, target_date

    @staticmethod
    def evaluate_inertia(df, target_date):
        """
        Avalia o dataset carregado para validar se há o mínimo de 30 dias
        e qual a inércia real disponível.
        """
        if df is None or df.empty or "DateTime" not in df.columns:
            return {"valid": False, "months": 0, "status": "Sem dados no banco"}

        # Garante que target_date seja objeto date para evitar erro de tipo na subtração
        if isinstance(target_date, datetime):
            target_date = target_date.date()

        # Normaliza as datas do DataFrame para cálculo
        if pd.api.types.is_datetime64_any_dtype(df["DateTime"]):
             temp_dates = df["DateTime"]
             if temp_dates.dt.tz is not None:
                 temp_dates = temp_dates.dt.tz_localize(None)
        else:
             temp_dates = pd.to_datetime(df["DateTime"]).dt.tz_localize(None)

        start_date_found = temp_dates.min().date()
        
        # Diferença em dias (date - date)
        total_days = (target_date - start_date_found).days
        
        if total_days < 30:
            return {
                "valid": False, 
                "months": 0, 
                "days": total_days, 
                "status": f"Dados insuficientes: apenas {total_days} dias encontrados.",
                "start_date": start_date_found
            }

        inertia_days = max(0, total_days - 30)
        inertia_months = min(12, inertia_days // 30)

        if inertia_months >= 12:
            status = "Inércia Completa (13 meses totais)"
        elif inertia_months >= 1:
            status = f"Inércia Parcial ({inertia_months + 1} meses totais)"
        else:
            status = "Sem Inércia (Apenas janela de análise disponível)"

        return {
            "valid": True,
            "months": inertia_months,
            "days": total_days,
            "status": status,
            "start_date": start_date_found
        }