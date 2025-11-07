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
    
    Para números brasileiros, tenta buscar com e sem o 9º dígito.
    
    Args:
        db: Cliente Firestore
        tenant_id: ID do tenant
        user_id: ID do usuário (número de telefone)
        
    Returns:
        Tupla (documento do contato, user_id usado para encontrar) ou (None, None) se não encontrado
        O documento sempre é retornado (mesmo que não exista), mas None indica que não foi encontrado
    """
    logging.info(f"[_find_contact_by_phone] INÍCIO: user_id={user_id}, tenant_id={tenant_id}")
    
    # Normalizar número (remover +)
    logging.info(f"[_find_contact_by_phone] Normalizando número: user_id={user_id}")
    normalized = _normalize_phone_number(user_id)
    logging.info(f"[_find_contact_by_phone] Número normalizado: {normalized}")
    
    # Gerar variações do número
    logging.info(f"[_find_contact_by_phone] Gerando variações do número...")
    variations = _generate_phone_variations(normalized)
    logging.info(f"[_find_contact_by_phone] Variações geradas: {variations} (total: {len(variations)})")
    
    # Tentar buscar cada variação
    logging.info(f"[_find_contact_by_phone] Iniciando busca por variações...")
    for idx, phone_variant in enumerate(variations, 1):
        logging.info(f"[_find_contact_by_phone] Tentativa {idx}/{len(variations)}: buscando variação '{phone_variant}'")
        try:
            collection_path = f'tenants/{tenant_id}/contacts'
            logging.info(f"[_find_contact_by_phone] Caminho da coleção: {collection_path}")
            contact_doc_ref = db.collection(collection_path).document(phone_variant)
            logging.info(f"[_find_contact_by_phone] Referência do documento criada: {contact_doc_ref.path}")
            
            logging.info(f"[_find_contact_by_phone] Buscando documento no Firestore...")
            contact_doc = contact_doc_ref.get()
            logging.info(f"[_find_contact_by_phone] Documento obtido: exists={contact_doc.exists}")
            
            if contact_doc.exists:
                logging.info(f"[_find_contact_by_phone] ✓ Contato encontrado com variação: {phone_variant} (original: {user_id})")
                contact_data = contact_doc.to_dict()
                logging.info(f"[_find_contact_by_phone] Dados do contato encontrado: {contact_data}")
                return contact_doc, phone_variant
            else:
                logging.info(f"[_find_contact_by_phone] ✗ Documento não existe para variação: {phone_variant}")
        except Exception as e:
            logging.warning(f"[_find_contact_by_phone] ERRO ao buscar contato com variação {phone_variant}: {e}", exc_info=True)
            continue
    
    # Não encontrou em nenhuma variação, retornar None para indicar que não foi encontrado
    logging.info(f"[_find_contact_by_phone] ✗ Contato não encontrado para nenhuma variação de {user_id}")
    logging.info(f"[_find_contact_by_phone] FIM: retornando (None, None)")
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
        logging.info("=" * 80)
        logging.info("INÍCIO: execute_business_routing")
        logging.info(f"Parâmetros recebidos: tenant_id={tenant_id}, user_id={user_id}, channel_id={channel_id}, message_text='{message_text[:50]}...'")
        logging.info("=" * 80)
        
        # FASE 1: Inicializar cliente Firestore
        logging.info("[FASE 1] Inicializando cliente Firestore...")
        db = _get_firestore_client()
        logging.info("[FASE 1] Cliente Firestore inicializado com sucesso")
        
        # FASE 2: Buscar contato
        logging.info("[FASE 2] Iniciando busca de contato...")
        logging.info(f"[FASE 2] Parâmetros da busca: user_id={user_id}, tenant_id={tenant_id}")
        contact_doc, found_phone_id = _find_contact_by_phone(db, tenant_id, user_id)
        logging.info(f"[FASE 2] Resultado da busca: contact_doc={contact_doc}, found_phone_id={found_phone_id}")
        
        # Verificar se contato foi encontrado
        if contact_doc is None:
            logging.warning("[FASE 2] contact_doc é None - contato não encontrado")
            logging.warning(f"[FASE 2] Finalizando sem enviar para Dialogflow. user_id={user_id}")
            return None
        
        if not contact_doc.exists:
            logging.warning("[FASE 2] contact_doc.exists é False - contato não encontrado")
            logging.warning(f"[FASE 2] Finalizando sem enviar para Dialogflow. user_id={user_id}")
            return None
        
        logging.info(f"[FASE 2] Contato encontrado! found_phone_id={found_phone_id}")
        
        # FASE 3: Extrair dados do contato
        logging.info("[FASE 3] Extraindo dados do contato...")
        contact_data = contact_doc.to_dict()
        logging.info(f"[FASE 3] contact_data completo: {contact_data}")
        
        status = contact_data.get("status", "bdr_inbound")
        score = contact_data.get("score", 0)
        context_score = contact_data.get("context_score", "Lead inbound (BDR Padrão)")
        name = contact_data.get("name", "")
        source_list = contact_data.get("source_list", "")
        
        logging.info(f"[FASE 3] Dados extraídos: status={status}, score={score}, context_score={context_score}, name={name}, source_list={source_list}")
        
        # FASE 4: Determinar funnel_id
        logging.info("[FASE 4] Determinando funnel_id...")
        funnel_id = "core_bdr"
        if status and status.startswith("sdr_"):
            funnel_id = "core_sdr"
            logging.info(f"[FASE 4] Status '{status}' começa com 'sdr_', usando funnel_id='{funnel_id}'")
        else:
            logging.info(f"[FASE 4] Status '{status}' não começa com 'sdr_', usando funnel_id='{funnel_id}'")
        
        logging.info(f"[FASE 4] funnel_id determinado: {funnel_id}")
        
        # FASE 5: Buscar configuração do tenant
        logging.info("[FASE 5] Buscando configuração do tenant...")
        logging.info(f"[FASE 5] Buscando tenant_id={tenant_id}")
        tenant_doc_ref = db.collection('tenants').document(tenant_id)
        tenant_doc = tenant_doc_ref.get()
        logging.info(f"[FASE 5] tenant_doc obtido: exists={tenant_doc.exists}")
        
        if not tenant_doc.exists:
            logging.error(f"[FASE 5] Tenant {tenant_id} não encontrado no Firestore")
            return None
        
        tenant_data = tenant_doc.to_dict()
        logging.info(f"[FASE 5] tenant_data obtido: {list(tenant_data.keys()) if tenant_data else 'None'}")
        
        all_configs = tenant_data.get('playbook_configs', {})
        logging.info(f"[FASE 5] all_configs obtido: {list(all_configs.keys()) if all_configs else 'None'}")
        
        if not all_configs:
            logging.error(f"[FASE 5] Tenant {tenant_id} não possui playbook_configs configurado")
            return None
        
        playbook_config_to_use = all_configs.get(funnel_id)
        logging.info(f"[FASE 5] playbook_config_to_use para funnel_id '{funnel_id}': {playbook_config_to_use}")
        
        if playbook_config_to_use is None:
            logging.error(f"[FASE 5] Tenant {tenant_id} não possui configuração para funnel_id '{funnel_id}'")
            return None

        if not isinstance(playbook_config_to_use, dict):
            logging.error(f"[FASE 5] playbook_config_to_use não é um mapa/dict válido: tipo={type(playbook_config_to_use)}")
            return None

        logging.info(f"[FASE 5] playbook_config_to_use encontrado: {type(playbook_config_to_use)}")

        raw_playbook_status = playbook_config_to_use.get("status")
        playbook_is_active = _to_bool(raw_playbook_status)
        logging.info(
            f"[FASE 5] status do playbook (raw={raw_playbook_status}, bool={playbook_is_active}) para funnel_id='{funnel_id}'"
        )

        if not playbook_is_active:
            logging.error(
                f"[FASE 5] Playbook '{funnel_id}' está inativo (status={raw_playbook_status}). "
                "Encerrando processamento sem enviar ao Dialogflow."
            )
            return None
        
        # FASE 6: Extrair campos do playbook_config
        logging.info("[FASE 6] Extraindo campos do playbook_config...")
        IGNORED_FIELDS = {
            "core_active", "active", "enabled", "status", 
            "is_active", "core_enabled", "playbook_active"
        }
        logging.info(f"[FASE 6] Campos ignorados: {IGNORED_FIELDS}")
        
        playbook_params = {}
        if isinstance(playbook_config_to_use, dict):
            logging.info(f"[FASE 6] playbook_config_to_use é dict com {len(playbook_config_to_use)} campos")
            for key, value in playbook_config_to_use.items():
                if key.lower() not in [f.lower() for f in IGNORED_FIELDS]:
                    playbook_params[f"playbook_{key}"] = value
                    logging.info(f"[FASE 6] Campo adicionado: playbook_{key}={value} (tipo: {type(value)})")
                else:
                    logging.info(f"[FASE 6] Campo ignorado: {key}")
        else:
            logging.warning(f"[FASE 6] playbook_config_to_use não é dict: {type(playbook_config_to_use)}")
        
        logging.info(f"[FASE 6] playbook_params final: {list(playbook_params.keys())}")
        
        # FASE 7: Preparar session_params
        logging.info("[FASE 7] Preparando session_params...")
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
            "source_list": source_list
        }
        logging.info(f"[FASE 7] session_params criado com {len(session_params)} campos:")
        for key, value in session_params.items():
            logging.info(f"[FASE 7]   {key}={value} (tipo: {type(value)})")
        
        # FASE 8: Verificar configuração do Dialogflow
        logging.info("[FASE 8] Verificando configuração do Dialogflow...")
        logging.info(f"[FASE 8] PROJECT_ID={PROJECT_ID}, LOCATION={LOCATION}, AGENT_ID={AGENT_ID}")
        
        if not AGENT_ID:
            logging.error("[FASE 8] DIALOGFLOW_AGENT_ID não está configurado")
            return None
        
        # FASE 9: Inicializar cliente Dialogflow
        logging.info("[FASE 9] Inicializando cliente Dialogflow...")
        dialogflow_client = _get_dialogflow_client()
        logging.info("[FASE 9] Cliente Dialogflow inicializado com sucesso")
        
        # FASE 10: Criar session_path
        logging.info("[FASE 10] Criando session_path...")
        session_path = dialogflow_client.session_path(PROJECT_ID, LOCATION, AGENT_ID, user_id)
        logging.info(f"[FASE 10] session_path criado: {session_path}")
        
        # FASE 11: Criar text_input e query_input
        logging.info("[FASE 11] Criando text_input e query_input...")
        text_input = TextInput(text=message_text)
        logging.info(f"[FASE 11] text_input criado: text='{message_text[:50]}...'")
        query_input = QueryInput(text=text_input, language_code="pt-br")
        logging.info(f"[FASE 11] query_input criado: language_code='pt-br'")
        
        # FASE 12: Converter session_params para struct_params
        logging.info("[FASE 12] Convertendo session_params para struct_params...")
        struct_params = struct_pb2.Struct()
        logging.info(f"[FASE 12] struct_params criado: {type(struct_params)}")
        
        for key, value in session_params.items():
            logging.info(f"[FASE 12] Processando campo: {key}={value} (tipo: {type(value)})")
            if isinstance(value, (dict, list)):
                converted_value = json.dumps(value, ensure_ascii=False)
                struct_params[key] = converted_value
                logging.info(f"[FASE 12]   Campo {key} convertido de {type(value)} para JSON string: '{converted_value[:50]}...'")
            elif isinstance(value, (int, float)):
                converted_value = str(value)
                struct_params[key] = converted_value
                logging.info(f"[FASE 12]   Campo {key} convertido de {type(value)} para string: '{converted_value}'")
            elif isinstance(value, bool):
                converted_value = str(value).lower()
                struct_params[key] = converted_value
                logging.info(f"[FASE 12]   Campo {key} convertido de {type(value)} para string: '{converted_value}'")
            elif value is None:
                logging.info(f"[FASE 12]   Campo {key} é None, ignorando")
                continue
            else:
                converted_value = str(value)
                struct_params[key] = converted_value
                logging.info(f"[FASE 12]   Campo {key} convertido para string: '{converted_value[:50]}...'")
        
        logging.info(f"[FASE 12] struct_params populado com {len(struct_params)} campos")
        
        # FASE 13: Criar QueryParameters
        logging.info("[FASE 13] Criando QueryParameters...")
        query_params = session.QueryParameters()
        logging.info(f"[FASE 13] query_params criado: {type(query_params)}")
        logging.info(f"[FASE 13] query_params.parameters ANTES da verificação: {query_params.parameters}")
        logging.info(f"[FASE 13] query_params.parameters é None? {query_params.parameters is None}")
        logging.info(f"[FASE 13] query_params.parameters tipo: {type(query_params.parameters)}")
        
        if query_params.parameters is None:
            logging.info("[FASE 13] query_params.parameters é None, criando novo Struct...")
            query_params.parameters = struct_pb2.Struct()
            logging.info(f"[FASE 13] Novo struct criado: {type(query_params.parameters)}")
        else:
            logging.info(f"[FASE 13] query_params.parameters já existe: {type(query_params.parameters)}")
        
        logging.info(f"[FASE 13] query_params.parameters DEPOIS da verificação: {query_params.parameters}")
        logging.info(f"[FASE 13] Tentando fazer update de struct_params em query_params.parameters...")
        logging.info(f"[FASE 13] struct_params tipo: {type(struct_params)}, valor: {struct_params}")
        logging.info(f"[FASE 13] query_params.parameters tipo: {type(query_params.parameters)}, valor: {query_params.parameters}")
        
        try:
            query_params.parameters.update(struct_params)
            logging.info(f"[FASE 13] update() executado com sucesso!")
            logging.info(f"[FASE 13] query_params.parameters após update: {query_params.parameters}")
        except Exception as e:
            logging.error(f"[FASE 13] ERRO ao executar update(): {e}", exc_info=True)
            raise
        
        # FASE 14: Criar DetectIntentRequest
        logging.info("[FASE 14] Criando DetectIntentRequest...")
        request = DetectIntentRequest(
            session=session_path,
            query_input=query_input,
            query_params=query_params
        )
        logging.info(f"[FASE 14] DetectIntentRequest criado: session={session_path}")
        logging.info(f"[FASE 14] request.query_params: {request.query_params}")
        logging.info(f"[FASE 14] request.query_params.parameters: {request.query_params.parameters if request.query_params else 'None'}")
        
        # FASE 15: Chamar API do Dialogflow
        logging.info("[FASE 15] Chamando API do Dialogflow CX...")
        try:
            response = dialogflow_client.detect_intent(request=request)
            logging.info("[FASE 15] Resposta recebida do Dialogflow CX")
            logging.info(f"[FASE 15] response.query_result: {response.query_result}")
        except Exception as e:
            logging.error(f"[FASE 15] ERRO ao chamar a API do Dialogflow CX: {e}", exc_info=True)
            return None
        
        # FASE 16: Extrair resposta de texto
        logging.info("[FASE 16] Extraindo resposta de texto...")
        response_messages = [
            " ".join(msg.text.text) 
            for msg in response.query_result.response_messages 
            if msg.text and msg.text.text
        ]
        logging.info(f"[FASE 16] response_messages extraídas: {len(response_messages)} mensagens")
        
        if not response_messages:
            logging.info("[FASE 16] Dialogflow CX não retornou uma resposta de texto")
            return None
        
        # FASE 17: Preparar resposta final
        logging.info("[FASE 17] Preparando resposta final...")
        response_text = " ".join(response_messages)
        logging.info(f"[FASE 17] response_text: '{response_text[:100]}...'")
        
        logging.info("=" * 80)
        logging.info("FIM: execute_business_routing - SUCESSO")
        logging.info(f"Resposta gerada para tenant_id={tenant_id}, user_id={user_id}")
        logging.info("=" * 80)
        return response_text
        
    except Exception as e:
        logging.error("=" * 80)
        logging.error("ERRO: execute_business_routing - FALHA")
        logging.error(f"Erro ao executar roteamento de negócio: {e}", exc_info=True)
        logging.error("=" * 80)
        return None

