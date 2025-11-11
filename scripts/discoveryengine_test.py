import os

from google.api_core.client_options import ClientOptions
from google.cloud import discoveryengine_v1 as discoveryengine

# ---------------------------------------------------------------------------
# Configurações (ajuste conforme necessário para o ambiente em teste)
# ---------------------------------------------------------------------------
PROJECT_ID = "128281034159"
LOCATION = "us"
ENGINE_ID = "81ce4df1-302f-48df-96a9-b621523f5f1f-search-1762880647"
SERVING_CONFIG_ID = "default_search"
DATA_STORE_ID = "saipos-rag-v3_1762885614793_gcs_store"
SEARCH_QUERY = "me fale sobre a empresa"


def search_with_filter_sample() -> discoveryengine.SearchResponse:
    """Executa uma busca no Discovery Engine filtrando por um data store."""

    client_options = (
        ClientOptions(api_endpoint=f"{LOCATION}-discoveryengine.googleapis.com")
        if LOCATION != "global"
        else None
    )

    client = discoveryengine.SearchServiceClient(client_options=client_options)

    serving_config = (
        f"projects/{PROJECT_ID}/locations/{LOCATION}/collections/default_collection"
        f"/engines/{ENGINE_ID}/servingConfigs/{SERVING_CONFIG_ID}"
    )

    data_store_path = (
        f"projects/{PROJECT_ID}/locations/{LOCATION}/collections/default_collection"
        f"/dataStores/{DATA_STORE_ID}"
    )

    snippet_spec = discoveryengine.SearchRequest.ContentSearchSpec.SnippetSpec(
        return_snippet=True,
        max_snippet_count=5,
    )

    summary_spec = discoveryengine.SearchRequest.ContentSearchSpec.SummarySpec(
        summary_result_count=3,
        include_citations=True,
        ignore_adversarial_query=True,
        model_prompt_spec=discoveryengine.SearchRequest.ContentSearchSpec.SummarySpec.ModelPromptSpec(
            preamble=(
                "Responda à pergunta do usuário de forma concisa e factual, "
                "baseando-se estritamente nos documentos fornecidos. "
                "Use o português do Brasil."
            )
        ),
    )

    extractive_content_spec = (
        discoveryengine.SearchRequest.ContentSearchSpec.ExtractiveContentSpec(
            max_extractive_answer_count=1,
            max_extractive_segment_count=5,
        )
    )

    content_search_spec = discoveryengine.SearchRequest.ContentSearchSpec(
        snippet_spec=snippet_spec,
        summary_spec=summary_spec,
        extractive_content_spec=extractive_content_spec,
    )

    spell_correction_spec = discoveryengine.SearchRequest.SpellCorrectionSpec(
        mode=discoveryengine.SearchRequest.SpellCorrectionSpec.Mode.AUTO
    )

    data_store_spec = discoveryengine.SearchRequest.DataStoreSpec(
        data_store=data_store_path
    )

    query_expansion_spec = discoveryengine.SearchRequest.QueryExpansionSpec(
        condition=discoveryengine.SearchRequest.QueryExpansionSpec.Condition.AUTO
    )

    request = discoveryengine.SearchRequest(
        serving_config=serving_config,
        query=SEARCH_QUERY,
        page_size=20,
        language_code="pt-BR",
        content_search_spec=content_search_spec,
        spell_correction_spec=spell_correction_spec,
        data_store_specs=[data_store_spec],
        query_expansion_spec=query_expansion_spec,
    )

    print(f"Buscando por '{SEARCH_QUERY}' apenas em '{DATA_STORE_ID}'...\n")
    response = client.search(request)

    results = list(response.results)
    if not results:
        print("Nenhum resultado retornado.")
    else:
    for index, result in enumerate(results, start=1):
        print(f"--- Resultado {index} ---")
        print(f"ID: {result.id}")
        document = result.document
        derived = document.derived_struct_data or {}
        snippet_shown = False
        print("Campos derivados:")
        for key, value in derived.items():
            if key == "snippets" and value:
                snippet_shown = True
                print("  - snippets:")
                for snippet_entry in value:
                    snippet_dict = dict(snippet_entry)
                    status = snippet_dict.get("snippet_status")
                    snippet_text = snippet_dict.get("snippet")
                    print(f"      status: {status}")
                    print(f"      texto: {snippet_text}")
            elif key in {"extractive_answers", "extractive_segments"} and value:
                print(f"  - {key}:")
                for segment in value:
                    segment_dict = dict(segment)
                    for seg_key, seg_value in segment_dict.items():
                        print(f"      {seg_key}: {seg_value}")
            else:
                print(f"  - {key}: {value}")
        if not snippet_shown:
            print("  - snippets: nenhum snippet retornado")
        print("-----\n")

    if not results:
        print("Crie o data store e aguarde a indexação antes de testar novamente.")

    if response.summary and response.summary.summary_text:
        print("Resumo gerado:")
        print(response.summary.summary_text)
        print("-----")
    elif response.summary and response.summary.summary_skipped_reasons:
        print("Resumo não gerado. Motivos:")
        for reason in response.summary.summary_skipped_reasons:
            print(f"  - {reason}")
        print("-----")

    return response


if __name__ == "__main__":
    # Requer: pip install google-cloud-discoveryengine
    search_with_filter_sample()

