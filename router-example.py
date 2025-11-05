import base64
import json
import os
import requests
import logging

from google.cloud.dialogflowcx_v3 import SessionsClient, QueryInput, TextInput, DetectIntentRequest


# --- Configurações Lidas de Variáveis de Ambiente ---
PROJECT_ID = os.environ.get("GCP_PROJECT")
LOCATION = os.environ.get("DIALOGFLOW_LOCATION", "us-central1")
AGENT_ID = os.environ.get("DIALOGFLOW_AGENT_ID")
WHATSAPP_TOKEN = os.environ.get("META_TOKEN_SEND")
WHATSAPP_API_VERSION = "v19.0"

# --- Inicialização dos Clientes ---
try:
    client_options = {"api_endpoint": f"{LOCATION}-dialogflow.googleapis.com"}
    dialogflow_client = SessionsClient(client_options=client_options)
except Exception as e:
    logging.error(f"Erro ao inicializar o cliente do Dialogflow: {e}")
    dialogflow_client = None

def send_whatsapp_message(phone_number, message_text, phone_number_id):
    """
    Função para enviar uma mensagem de texto de volta ao usuário no WhatsApp.
    """
    if not WHATSAPP_TOKEN:
        logging.error("WHATSAPP_TOKEN não está configurado.")
        return

    url = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    data = {
        "messaging_product": "whatsapp",
        "to": phone_number,
        "text": {"body": message_text},
    }
    
    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        logging.info(f"Resposta enviada com sucesso para {phone_number}")
        return response.json()
    except requests.exceptions.RequestException as e:
        logging.error(f"Erro ao enviar mensagem para o WhatsApp: {e}")
        return None


def process_dialogflow_message(request):
    """
    Função Cloud Function acionada por HTTP, esperando um push do Pub/Sub.
    """
    # 1. Extrair a mensagem do Pub/Sub do corpo da requisição HTTP
    if not request.is_json:
        logging.error("Requisição não é JSON, ignorando.")
        return "Requisição inválida.", 400

    request_json = request.get_json(silent=True)
    if not request_json or 'message' not in request_json:
        logging.error("Payload JSON inválido, sem campo 'message'.")
        return "Payload inválido.", 400

    event = request_json['message']
    
    if 'data' not in event:
        logging.error("Mensagem do Pub/Sub inválida, sem campo 'data'.")
        # Retorna 200 para o Pub/Sub não reenviar a mensagem com erro.
        return "Mensagem do Pub/Sub sem dados.", 200

    # 2. Decodificar a mensagem
    pubsub_message_str = base64.b64decode(event['data']).decode('utf-8')
    message_data = json.loads(pubsub_message_str)

    numero = message_data.get("numero")
    texto = message_data.get("texto")
    phone_number_id = message_data.get("phone_number_id")
    
    if not all([numero, texto, phone_number_id, dialogflow_client, AGENT_ID]):
        logging.error(f"Mensagem ou configuração inválida. Dados recebidos: {message_data}")
        return "Dados ou configuração inválidos.", 400

    # 3. Chamar o Dialogflow CX
    session_path = dialogflow_client.session_path(PROJECT_ID, LOCATION, AGENT_ID, numero)

    text_input = TextInput(text=texto)
    query_input = QueryInput(text=text_input, language_code="pt-br")

    request = DetectIntentRequest(
        session=session_path,
        query_input=query_input,
    )
    
    try:
        response = dialogflow_client.detect_intent(request=request)
    except Exception as e:
        logging.error(f"Erro ao chamar a API do Dialogflow: {e}")
        # Retorna 500 para indicar um erro interno.
        return "Erro interno ao processar no Dialogflow.", 500

    # 4. Extrair e enviar a resposta
    response_messages = [
        " ".join(msg.text.text) for msg in response.query_result.response_messages if msg.text
    ]
    
    if not response_messages:
        logging.info("Dialogflow não retornou uma resposta de texto.")
        return "OK", 204 # No content

    for reply in response_messages:
        send_whatsapp_message(numero, reply, phone_number_id)
        
    return "OK", 200


########################################################