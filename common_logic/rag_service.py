import logging
import os
import secrets
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import firebase_admin
from firebase_admin import firestore
from google.cloud import discoveryengine_v1alpha as discoveryengine
from google.cloud import secretmanager


class RagServiceError(Exception):
    """Erro base para o serviço de RAG."""


class RagUnauthorizedError(RagServiceError):
    """Erro para credenciais ou acesso não autorizado."""


class RagNotFoundError(RagServiceError):
    """Erro quando um recurso (tenant/playbook) não é encontrado."""


class RagConfigurationError(RagServiceError):
    """Erro quando há configuração incorreta ou ausente."""


@dataclass
class RagStoreTarget:
    """Representa um destino de busca RAG."""

    data_store_id: str
    location: str


@dataclass
class RagSearchResult:
    """Resultado da consulta ao RAG."""

    summary: str
    citations: List[Dict[str, Any]]


class RagSearchService:
    """Serviço para consultas dinâmicas ao Vertex AI Search (Discovery Engine)."""

    def __init__(self) -> None:
        self.project_id = (
            os.environ.get("GCP_PROJECT")
            or os.environ.get("GOOGLE_CLOUD_PROJECT")
            or os.environ.get("PROJECT_ID")
        )
        self.default_location = (
            os.environ.get("RAG_LOCATION")
            or os.environ.get("DISCOVERYENGINE_LOCATION")
            or "global"
        )
        self._db: Optional[firestore.Client] = None
        self._secret_client: Optional[secretmanager.SecretManagerServiceClient] = None
        self._search_clients: Dict[str, discoveryengine.SearchServiceClient] = {}
        self._cached_api_key: Optional[str] = None

        if not self.project_id:
            logging.warning(
                "[RagSearchService] PROJECT_ID não está configurado. "
                "Consultas ao Secret Manager ou ao Discovery Engine podem falhar."
            )

    # -------------------------------------------------------------------------
    # Clientes (singleton)
    # -------------------------------------------------------------------------
    def _get_firestore_client(self) -> firestore.Client:
        if self._db is None:
            try:
                if not firebase_admin._apps:
                    firebase_admin.initialize_app()
                self._db = firestore.client()
                logging.info("[RagSearchService] Cliente Firestore inicializado")
            except Exception as exc:
                logging.error(
                    "[RagSearchService] Erro ao inicializar Firestore: %s", exc
                )
                raise RagConfigurationError(
                    "Não foi possível inicializar o Firestore"
                ) from exc
        return self._db

    def _get_secret_client(self) -> secretmanager.SecretManagerServiceClient:
        if self._secret_client is None:
            try:
                self._secret_client = secretmanager.SecretManagerServiceClient()
                logging.info("[RagSearchService] Cliente Secret Manager inicializado")
            except Exception as exc:
                logging.error(
                    "[RagSearchService] Erro ao inicializar Secret Manager: %s", exc
                )
                raise RagConfigurationError(
                    "Não foi possível inicializar o Secret Manager"
                ) from exc
        return self._secret_client

    def _get_search_client(
        self, location: str
    ) -> discoveryengine.SearchServiceClient:
        location_key = location or self.default_location
        if location_key not in self._search_clients:
            try:
                endpoint = (
                    f"{location_key}-discoveryengine.googleapis.com"
                    if location_key != "global"
                    else "global-discoveryengine.googleapis.com"
                )
                client_options = {"api_endpoint": endpoint}
                self._search_clients[location_key] = discoveryengine.SearchServiceClient(
                    client_options=client_options
                )
                logging.info(
                    "[RagSearchService] Cliente Discovery Engine inicializado. "
                    "location=%s endpoint=%s",
                    location_key,
                    endpoint,
                )
            except Exception as exc:
                logging.error(
                    "[RagSearchService] Erro ao inicializar Discovery Engine: %s", exc
                )
                raise RagConfigurationError(
                    "Não foi possível inicializar o Discovery Engine"
                ) from exc
        return self._search_clients[location_key]

    # -------------------------------------------------------------------------
    # Segurança (API Key)
    # -------------------------------------------------------------------------
    def _load_api_key(self) -> str:
        if self._cached_api_key:
            return self._cached_api_key

        api_key = os.environ.get("RAG_API_KEY")
        secret_name = os.environ.get("RAG_API_SECRET_NAME")

        if secret_name:
            if not self.project_id:
                raise RagConfigurationError(
                    "PROJECT_ID não definido para uso do Secret Manager"
                )
            secret_path = f"projects/{self.project_id}/secrets/{secret_name}/versions/latest"
            try:
                response = self._get_secret_client().access_secret_version(
                    request={"name": secret_path}
                )
                api_key = response.payload.data.decode("utf-8").strip()
                logging.info(
                    "[RagSearchService] API key carregada do Secret Manager (%s)",
                    secret_name,
                )
            except Exception as exc:
                logging.error(
                    "[RagSearchService] Erro ao carregar API key do Secret Manager: %s",
                    exc,
                )
                raise RagConfigurationError(
                    "Falha ao carregar a chave de API do Secret Manager"
                ) from exc

        if not api_key:
            raise RagConfigurationError(
                "Chave de API para o endpoint de RAG não está configurada"
            )

        self._cached_api_key = api_key
        return api_key

    def verify_api_key(self, provided_key: Optional[str]) -> None:
        if provided_key is None:
            logging.warning("[RagSearchService] X-Api-Key ausente")
            raise RagUnauthorizedError("Cabeçalho X-Api-Key é obrigatório")

        expected = self._load_api_key()
        if not secrets.compare_digest(provided_key.strip(), expected):
            logging.warning("[RagSearchService] X-Api-Key inválida")
            raise RagUnauthorizedError("API Key inválida")

    # -------------------------------------------------------------------------
    # Resolução de Data Store
    # -------------------------------------------------------------------------
    @staticmethod
    def _is_truthy(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.strip().lower() in {"true", "1", "yes", "y", "on", "sim"}
        return False

    def _extract_targets_from_playbooks(
        self, playbook_configs: Dict[str, Any]
    ) -> Dict[str, RagStoreTarget]:
        targets: Dict[str, RagStoreTarget] = {}
        for playbook_name, playbook_cfg in playbook_configs.items():
            if not isinstance(playbook_cfg, dict):
                continue
            data_store_id = playbook_cfg.get("rag_datastore_id") or playbook_cfg.get(
                "rag_id"
            )
            if not data_store_id:
                continue
            location = (
                playbook_cfg.get("rag_location")
                or playbook_cfg.get("rag_region")
                or self.default_location
            )
            targets[playbook_name] = RagStoreTarget(
                data_store_id=data_store_id, location=location
            )
        return targets

    def _extract_targets_from_rag_configs(
        self, rag_configs: Dict[str, Any]
    ) -> Dict[str, RagStoreTarget]:
        targets: Dict[str, RagStoreTarget] = {}
        for alias, rag_cfg in rag_configs.items():
            if not isinstance(rag_cfg, dict):
                continue
            data_store_id = rag_cfg.get("data_store_id") or rag_cfg.get(
                "rag_datastore_id"
            )
            if not data_store_id:
                continue
            location = (
                rag_cfg.get("location")
                or rag_cfg.get("region")
                or self.default_location
            )
            targets[alias] = RagStoreTarget(
                data_store_id=data_store_id, location=location
            )
        return targets

    def resolve_store_target(
        self,
        tenant_id: str,
        playbook_name: Optional[str],
        rag_identifier: Optional[str],
        explicit_data_store_id: Optional[str],
    ) -> RagStoreTarget:
        db = self._get_firestore_client()
        tenant_doc = db.collection("tenants").document(tenant_id).get()

        if not tenant_doc.exists:
            logging.warning(
                "[RagSearchService] Tenant não encontrado: tenant_id=%s", tenant_id
            )
            raise RagNotFoundError(f"Tenant '{tenant_id}' não encontrado")

        tenant_data = tenant_doc.to_dict() or {}

        playbook_targets = self._extract_targets_from_playbooks(
            tenant_data.get("playbook_configs", {})
        )
        rag_targets = self._extract_targets_from_rag_configs(
            tenant_data.get("rag_configs", {})
        )

        allowed_targets: Dict[str, RagStoreTarget] = {}

        # Targets informados por playbooks (chave = playbook_name)
        allowed_targets.update(playbook_targets)

        # Targets adicionais mapeados por alias (chave = alias)
        allowed_targets.update(rag_targets)

        # Targets acessíveis diretamente pelo ID do data store
        for target in list(playbook_targets.values()) + list(rag_targets.values()):
            allowed_targets[target.data_store_id] = target

        if explicit_data_store_id:
            target = allowed_targets.get(explicit_data_store_id)
            if not target:
                logging.warning(
                    "[RagSearchService] Data store não autorizado. tenant_id=%s id=%s",
                    tenant_id,
                    explicit_data_store_id,
                )
                raise RagUnauthorizedError("Data store não autorizado para este tenant")
            return target

        if playbook_name:
            target = playbook_targets.get(playbook_name)
            if not target:
                logging.warning(
                    "[RagSearchService] Playbook não encontrado. tenant_id=%s playbook=%s",
                    tenant_id,
                    playbook_name,
                )
                raise RagNotFoundError(
                    f"Playbook '{playbook_name}' não foi configurado para o tenant"
                )

            # Garantir que o playbook está ativo
            playbook_cfg = (tenant_data.get("playbook_configs") or {}).get(
                playbook_name
            )
            if playbook_cfg and not self._is_truthy(playbook_cfg.get("status", True)):
                logging.warning(
                    "[RagSearchService] Playbook inativo. tenant_id=%s playbook=%s",
                    tenant_id,
                    playbook_name,
                )
                raise RagConfigurationError(
                    f"Playbook '{playbook_name}' está inativo para o tenant"
                )
            return target

        if rag_identifier:
            target = allowed_targets.get(rag_identifier)
            if not target:
                logging.warning(
                    "[RagSearchService] RAG identifier não autorizado. tenant_id=%s identifier=%s",
                    tenant_id,
                    rag_identifier,
                )
                raise RagUnauthorizedError(
                    "Identificador de RAG não autorizado para este tenant"
                )
            return target

        logging.warning(
            "[RagSearchService] Nenhum identificador de data store informado"
        )
        raise RagConfigurationError(
            "Informe playbook_name, rag_identifier ou data_store_id"
        )

    # -------------------------------------------------------------------------
    # Consulta ao Discovery Engine
    # -------------------------------------------------------------------------
    def search(
        self,
        target: RagStoreTarget,
        query: str,
        summary_result_count: int = 1,
        include_citations: bool = False,
    ) -> RagSearchResult:
        if not query or not query.strip():
            raise RagConfigurationError("Query não pode ser vazia")

        summary_result_count = max(1, min(summary_result_count, 5))
        location = target.location or self.default_location
        client = self._get_search_client(location)

        serving_config_path = client.serving_config_path(
            project=self.project_id,
            location=location,
            data_store=target.data_store_id,
            serving_config="default_config",
        )

        try:
            search_request = discoveryengine.SearchRequest(
                serving_config=serving_config_path,
                query=query,
                page_size=10,
                content_search_spec=discoveryengine.SearchRequest.ContentSearchSpec(
                    summary_spec=discoveryengine.SearchRequest.ContentSearchSpec.SummarySpec(
                        summary_result_count=summary_result_count,
                        include_citations=include_citations,
                        ignore_adversarial_query=True,
                    )
                ),
            )
            response = client.search(request=search_request)
        except Exception as exc:
            logging.error(
                "[RagSearchService] Erro ao consultar Discovery Engine: %s", exc
            )
            raise RagServiceError("Falha ao consultar o mecanismo de busca") from exc

        summary_text = ""
        citations: List[Dict[str, Any]] = []

        if response.summary and response.summary.summary_text:
            summary_text = response.summary.summary_text
        else:
            summary_text = (
                "Não encontrei uma resposta direta para essa pergunta nos meus documentos."
            )

        if include_citations and response.summary and response.summary.reference_info:
            reference_info = response.summary.reference_info
            for citation in getattr(reference_info, "citations", []):
                citation_entry = {}
                anchor = getattr(citation, "anchor", None)
                uri = getattr(citation, "uri", None)
                reference = getattr(citation, "reference", None)
                if anchor:
                    citation_entry["anchor"] = anchor
                if uri:
                    citation_entry["uri"] = uri
                if reference:
                    citation_entry["reference"] = reference
                if citation_entry:
                    citations.append(citation_entry)

        return RagSearchResult(summary=summary_text, citations=citations)

    # -------------------------------------------------------------------------
    # Facade principal
    # -------------------------------------------------------------------------
    def run_query(
        self,
        *,
        tenant_id: str,
        query: str,
        playbook_name: Optional[str] = None,
        rag_identifier: Optional[str] = None,
        data_store_id: Optional[str] = None,
        summary_result_count: int = 1,
        include_citations: bool = False,
        api_key: Optional[str] = None,
    ) -> RagSearchResult:
        self.verify_api_key(api_key)

        target = self.resolve_store_target(
            tenant_id=tenant_id,
            playbook_name=playbook_name,
            rag_identifier=rag_identifier,
            explicit_data_store_id=data_store_id,
        )

        return self.search(
            target=target,
            query=query,
            summary_result_count=summary_result_count,
            include_citations=include_citations,
        )


