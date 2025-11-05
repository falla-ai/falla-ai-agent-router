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
    
    Para números brasileiros, tenta buscar com e sem o 9º dígito.
    
    Args:
        db: Cliente Firestore
        tenant_id: ID do tenant
        user_id: ID do usuário (número de telefone)
        
    Returns:
        Tupla (documento do contato, user_id usado para encontrar) ou (None, None) se não encontrado
        O documento sempre é retornado (mesmo que não exista), mas None indica que não foi encontrado
    """
    # Normalizar número (remover +)
    normalized = _normalize_phone_number(user_id)
    
    # Gerar variações do número
    variations = _generate_phone_variations(normalized)
    
    logging.debug(f"Buscando contato com variações: {variations[:3]}...")  # Log apenas primeiras 3
    
    # Tentar buscar cada variação
    for phone_variant in variations:
        try:
            contact_doc_ref = db.collection(f'tenants/{tenant_id}/contacts').document(phone_variant)
            contact_doc = contact_doc_ref.get()
            
            if contact_doc.exists:
                logging.info(f"Contato encontrado com variação: {phone_variant} (original: {user_id})")
                return contact_doc, phone_variant
        except Exception as e:
            logging.warning(f"Erro ao buscar contato com variação {phone_variant}: {e}")
            continue
    
    # Não encontrou em nenhuma variação, retornar None para indicar que não foi encontrado
    logging.info(f"Contato não encontrado para nenhuma variação de {user_id}")
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
        Texto da resposta do agente ou None em caso de falha
    """
    try:
        db = _get_firestore_client()
        
        # Lookup 2: Roteamento de Funil e Enriquecimento (Firestore)
        # Buscar contato tentando variações do número (com/sem 9º dígito para números brasileiros)
        contact_doc, found_phone_id = _find_contact_by_phone(db, tenant_id, user_id)
        
        # Valores padrão BDR
        funnel_id = "core_bdr"
        score = 0  # Number conforme estrutura Firestore
        context_score = "Lead inbound (BDR Padrão)"
        status = "bdr_inbound"
        
        if contact_doc is not None and contact_doc.exists:
            contact_data = contact_doc.to_dict()
            
            # Atualizar valores com fallbacks (usando nomes corretos do Firestore)
            status = contact_data.get("status", status)
            score = contact_data.get("score", score)
            context_score = contact_data.get("context_score", context_score)
            
            # Lógica de roteamento: Se status começa com "sdr_", usar funnel "core_sdr"
            if status and status.startswith("sdr_"):
                funnel_id = "core_sdr"
        else:
            # Criar documento com valores padrão se não existir
            # Usar o número encontrado (se houver) ou o original normalizado (sem +)
            if found_phone_id:
                contact_phone_id = found_phone_id
            else:
                # Normalizar número original (remover +) para usar como ID do documento
                contact_phone_id = _normalize_phone_number(user_id)
            
            contact_doc_ref = db.collection(f'tenants/{tenant_id}/contacts').document(contact_phone_id)
            contact_doc_ref.set({
                "status": status,
                "score": score,
                "context_score": context_score
            })
            logging.info(f"Documento de contato criado para {contact_phone_id} (original: {user_id}) com valores padrão BDR")
        
        # Lookup 3: Configuração do Agente (Firestore)
        tenant_doc_ref = db.collection('tenants').document(tenant_id)
        tenant_doc = tenant_doc_ref.get()
        
        if not tenant_doc.exists:
            logging.error(f"Tenant {tenant_id} não encontrado no Firestore")
            return None
        
        tenant_data = tenant_doc.to_dict()
        all_configs = tenant_data.get('playbook_configs', {})
        
        if not all_configs:
            logging.error(f"Tenant {tenant_id} não possui playbook_configs configurado")
            return None
        
        playbook_config_to_use = all_configs.get(funnel_id)
        
        if playbook_config_to_use is None:
            logging.error(f"Tenant {tenant_id} não possui configuração para funnel_id '{funnel_id}'")
            return None
        
        # Campos que devem ser ignorados (não enviar ao Dialogflow)
        # Estes são campos de controle/status que o Dialogflow não precisa saber
        IGNORED_FIELDS = {
            "core_active", "active", "enabled", "status", 
            "is_active", "core_enabled", "playbook_active"
        }
        
        # Extrair campos relevantes do playbook_config individualmente
        # Cada campo será enviado como parâmetro separado com prefixo "playbook_"
        playbook_params = {}
        if isinstance(playbook_config_to_use, dict):
            for key, value in playbook_config_to_use.items():
                # Ignorar campos de status/controle
                if key.lower() not in [f.lower() for f in IGNORED_FIELDS]:
                    # Adicionar com prefixo "playbook_" para evitar conflitos
                    playbook_params[f"playbook_{key}"] = value
        
        # Preparação dos parâmetros do Dialogflow
        session_params = {
            "tenant_id": tenant_id,
            "channel_id": channel_id,
            "user_id": user_id,
            "playbook_name": funnel_id,
            # Campos individuais do playbook_config (ex: playbook_rag_id, playbook_tone_prompt)
            **playbook_params,
            # Campos do contato (usando nomes corretos do Firestore)
            "status": status,
            "score": score,
            "context_score": context_score
        }
        
        # Chamada do Dialogflow CX
        if not AGENT_ID:
            logging.error("DIALOGFLOW_AGENT_ID não está configurado")
            return None
        
        dialogflow_client = _get_dialogflow_client()
        session_path = dialogflow_client.session_path(PROJECT_ID, LOCATION, AGENT_ID, user_id)
        
        text_input = TextInput(text=message_text)
        query_input = QueryInput(text=text_input, language_code="pt-br")
        
        # Converter session_params para formato Struct do Dialogflow
        # O Dialogflow CX aceita parâmetros como Struct (protobuf)
        # Todos os valores são convertidos para string (Dialogflow trabalha com strings)
        struct_params = struct_pb2.Struct()
        
        for key, value in session_params.items():
            if isinstance(value, (dict, list)):
                # Converter objetos complexos para JSON string
                struct_params[key] = json.dumps(value, ensure_ascii=False)
            elif isinstance(value, (int, float)):
                # Números: converter para string (Dialogflow aceita string)
                struct_params[key] = str(value)
            elif isinstance(value, bool):
                # Booleanos: converter para string lowercase
                struct_params[key] = str(value).lower()  # "true" ou "false"
            elif value is None:
                # Ignorar valores None
                continue
            else:
                # Strings e outros tipos: converter para string
                struct_params[key] = str(value)
        
        # Criar QueryParameters com os parâmetros
        query_params = session.QueryParameters()
        query_params.parameters.update(struct_params)
        
        request = DetectIntentRequest(
            session=session_path,
            query_input=query_input,
            query_params=query_params
        )
        
        try:
            response = dialogflow_client.detect_intent(request=request)
        except Exception as e:
            logging.error(f"Erro ao chamar a API do Dialogflow CX: {e}")
            return None
        
        # Extrair resposta de texto
        response_messages = [
            " ".join(msg.text.text) 
            for msg in response.query_result.response_messages 
            if msg.text and msg.text.text
        ]
        
        if not response_messages:
            logging.info("Dialogflow CX não retornou uma resposta de texto")
            return None
        
        # Retornar a primeira resposta (ou concatenar todas se necessário)
        response_text = " ".join(response_messages)
        
        logging.info(f"Roteamento de negócio executado com sucesso para tenant_id={tenant_id}, user_id={user_id}")
        return response_text
        
    except Exception as e:
        logging.error(f"Erro ao executar roteamento de negócio: {e}", exc_info=True)
        return None

