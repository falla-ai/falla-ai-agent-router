"""
Módulo de roteamento de negócio compartilhado.
Implementa a lógica de roteamento de mensagens usando Firestore e Dialogflow CX.
"""

import os
import json
import logging
from typing import Optional, Dict, Any

import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.dialogflowcx_v3 import SessionsClient, QueryInput, TextInput, DetectIntentRequest
from google.cloud.dialogflowcx_v3.types import session
from google.protobuf import struct_pb2

# Inicialização dos clientes (singleton)
_db = None
_dialogflow_client = None

# Configurações lidas de variáveis de ambiente
PROJECT_ID = os.environ.get("GCP_PROJECT")
LOCATION = os.environ.get("DIALOGFLOW_LOCATION", "us-central1")
AGENT_ID = os.environ.get("DIALOGFLOW_AGENT_ID")


def _get_firestore_client():
    """Retorna o cliente Firestore (singleton)."""
    global _db
    if _db is None:
        try:
            # Usa Application Default Credentials (ADC)
            if not firebase_admin._apps:
                firebase_admin.initialize_app()
            _db = firestore.client()
            logging.info("Cliente Firestore inicializado com sucesso")
        except Exception as e:
            logging.error(f"Erro ao inicializar o cliente Firestore: {e}")
            raise
    return _db


def _get_dialogflow_client():
    """Retorna o cliente Dialogflow CX (singleton)."""
    global _dialogflow_client
    if _dialogflow_client is None:
        try:
            client_options = {"api_endpoint": f"{LOCATION}-dialogflow.googleapis.com"}
            _dialogflow_client = SessionsClient(client_options=client_options)
            logging.info("Cliente Dialogflow CX inicializado com sucesso")
        except Exception as e:
            logging.error(f"Erro ao inicializar o cliente do Dialogflow CX: {e}")
            raise
    return _dialogflow_client


def _normalize_phone_number(phone: str) -> str:
    """
    Normaliza número de telefone removendo caracteres especiais.
    
    Args:
        phone: Número de telefone (pode ter + no início)
        
    Returns:
        Número normalizado (sem +)
    """
    return phone.lstrip('+').strip()


def _to_bool(value: Any) -> bool:
    """Converte diferentes representações para booleano."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        return normalized in {"true", "1", "yes", "sim", "y", "on"}
    return False


def _generate_phone_variations(phone: str) -> list:
    """
    Gera variações do número de telefone para busca no Firestore.
    
    Para números brasileiros (começam com 55), gera variações com e sem o 9º dígito.
    Também adiciona variação com + no início.
    
    Args:
        phone: Número de telefone normalizado (sem +)
        
    Returns:
        Lista de variações do número para tentar buscar
    """
    variations = []
    
    # Adicionar variação original (sem +)
    variations.append(phone)
    
    # Adicionar variação com +
    variations.append(f"+{phone}")
    
    # Se é número brasileiro (começa com 55)
    if phone.startswith('55') and len(phone) >= 4:
        # Formato: 55 + DDD (2 dígitos) + número
        # Para números brasileiros celulares, o 9º dígito fica após o DDD
        
        if len(phone) == 12:
            # Número sem 9º dígito (12 dígitos: 55 + 2 DDD + 8 números)
            # Adicionar 9 na posição correta (após DDD)
            # Exemplo: 555195357522 -> 5551995357522
            ddd = phone[2:4]  # 2 dígitos do DDD
            number = phone[4:]  # Resto do número
            if len(number) == 8:  # Número de celular (8 dígitos)
                with_9th = f"55{ddd}9{number}"
                variations.append(with_9th)
                variations.append(f"+{with_9th}")
                logging.debug(f"Gerada variação com 9º dígito: {with_9th}")
        
        elif len(phone) == 13:
            # Número com 9º dígito (13 dígitos: 55 + 2 DDD + 9 + 8 números)
            # Remover 9 na posição 5 (após 55 + DDD)
            # Exemplo: 5551995357522 -> 555195357522
            if phone[4] == '9':  # Verifica se tem 9 na posição do 9º dígito
                without_9th = f"55{phone[2:4]}{phone[5:]}"
                variations.append(without_9th)
                variations.append(f"+{without_9th}")
                logging.debug(f"Gerada variação sem 9º dígito: {without_9th}")
    
    # Remover duplicatas mantendo ordem
    seen = set()
    unique_variations = []
    for var in variations:
        if var not in seen:
            seen.add(var)
            unique_variations.append(var)
    
    return unique_variations


def _find_contact_by_phone(db, tenant_id: str, user_id: str):
    """
    Busca contato no Firestore tentando variações do número de telefone.
    """
    normalized = _normalize_phone_number(user_id)
    variations = _generate_phone_variations(normalized)

    for phone_variant in variations:
        try:
            contact_doc = (
                db.collection(f"tenants/{tenant_id}/contacts")
                .document(phone_variant)
                .get()
            )
            if contact_doc.exists:
                logging.info(
                    "[_find_contact_by_phone] contato encontrado tenant=%s user=%s variant=%s",
                    tenant_id,
                    user_id,
                    phone_variant,
                )
                return contact_doc, phone_variant
        except Exception as e:
            logging.warning(
                "[_find_contact_by_phone] erro ao buscar variação %s: %s",
                phone_variant,
                e,
                exc_info=True,
            )
    logging.info(
        "[_find_contact_by_phone] contato não encontrado tenant=%s user=%s",
        tenant_id,
        user_id,
    )
    return None, None


def execute_business_routing(
    tenant_id: str,
    user_id: str,
    channel_id: str,
    message_text: str
) -> Optional[str]:
    """
    Função principal de roteamento de negócio.
    
    Args:
        tenant_id: ID do tenant
        user_id: ID do usuário (número de telefone em formato E.164)
        channel_id: ID do canal (WABA ID ou ID da Página)
        message_text: Texto da mensagem recebida
        
    Returns:
        Texto da resposta do agente ou None se contato não encontrado ou em caso de falha
    """
    try:
        logging.info(
            "[execute_business_routing] start tenant=%s user=%s channel=%s",
            tenant_id,
            user_id,
            channel_id,
        )

        db = _get_firestore_client()
        contact_doc, found_phone_id = _find_contact_by_phone(db, tenant_id, user_id)
        if contact_doc is None or not contact_doc.exists:
            logging.warning(
                "[execute_business_routing] contato não encontrado tenant=%s user=%s",
                tenant_id,
                user_id,
            )
            return None

        contact_data = contact_doc.to_dict()
        status = contact_data.get("status", "bdr_inbound")
        score = contact_data.get("score", 0)
        context_score = contact_data.get("context_score", "Lead inbound (BDR Padrão)")
        name = contact_data.get("name", "")
        source_list = contact_data.get("source_list", "")

        funnel_id = "core_bdr"
        if status and status.startswith("sdr_"):
            funnel_id = "core_sdr"

        logging.info(
            "[execute_business_routing] contato=%s funnel=%s status=%s score=%s",
            found_phone_id,
            funnel_id,
            status,
            score,
        )

        tenant_doc = db.collection("tenants").document(tenant_id).get()
        if not tenant_doc.exists:
            logging.error("[execute_business_routing] tenant não encontrado=%s", tenant_id)
            return None

        playbook_configs = tenant_doc.to_dict().get("playbook_configs", {})
        playbook_config = playbook_configs.get(funnel_id)
        if not playbook_config or not isinstance(playbook_config, dict):
            logging.error(
                "[execute_business_routing] playbook inválido tenant=%s funnel=%s",
                tenant_id,
                funnel_id,
            )
            return None

        if not _to_bool(playbook_config.get("status", True)):
            logging.warning(
                "[execute_business_routing] playbook inativo tenant=%s funnel=%s",
                tenant_id,
                funnel_id,
            )
            return None

        playbook_params = {
            f"playbook_{key}": value
            for key, value in playbook_config.items()
            if key.lower() not in {"core_active", "active", "enabled", "status", "is_active", "core_enabled", "playbook_active"}
        }

        session_params = {
            "tenant_id": tenant_id,
            "channel_id": channel_id,
            "user_id": user_id,
            "playbook_name": funnel_id,
            **playbook_params,
            "status": status,
            "score": score,
            "context_score": context_score,
            "name": name,
            "source_list": source_list,
        }

        if not AGENT_ID:
            logging.error("[execute_business_routing] variável DIALOGFLOW_AGENT_ID ausente")
            return None

        dialogflow_client = _get_dialogflow_client()
        session_path = dialogflow_client.session_path(PROJECT_ID, LOCATION, AGENT_ID, user_id)
        text_input = TextInput(text=message_text)
        query_input = QueryInput(text=text_input, language_code="pt-br")

        struct_params = struct_pb2.Struct()
        for key, value in session_params.items():
            if isinstance(value, (dict, list)):
                struct_params[key] = json.dumps(value, ensure_ascii=False)
            elif isinstance(value, (int, float)):
                struct_params[key] = str(value)
            elif isinstance(value, bool):
                struct_params[key] = str(value).lower()
            elif value is not None:
                struct_params[key] = str(value)

        query_params = session.QueryParameters()
        if query_params.parameters is None:
            query_params.parameters = struct_pb2.Struct()
        query_params.parameters.update(struct_params)

        request = DetectIntentRequest(
            session=session_path,
            query_input=query_input,
            query_params=query_params,
        )

        try:
            response = dialogflow_client.detect_intent(request=request)
        except Exception as e:
            logging.error("[execute_business_routing] erro no Dialogflow: %s", e, exc_info=True)
            return None

        response_messages = [
            " ".join(msg.text.text)
            for msg in response.query_result.response_messages
            if msg.text and msg.text.text
        ]
        if not response_messages:
            logging.info("[execute_business_routing] Dialogflow não retornou mensagem")
            return None

        response_text = " ".join(response_messages)
        logging.info(
            "[execute_business_routing] resposta gerada tenant=%s user=%s chars=%s",
            tenant_id,
            user_id,
            len(response_text),
        )
        return response_text

    except Exception as e:
        logging.error("[execute_business_routing] falha inesperada: %s", e, exc_info=True)
        return None

