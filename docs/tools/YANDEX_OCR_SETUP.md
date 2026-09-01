# Yandex Vision OCR setup

Short setup notes for enabling the Yandex OCR engine in Audion Office OCR AI.

## Official links

- Create a Yandex Cloud account and billing account: https://yandex.cloud/en/docs/billing/operations/create-new-account
- Payment methods for individuals: https://yandex.cloud/en/docs/billing/payment/payment-methods-individual
- Pay or top up a billing account: https://yandex.cloud/en/docs/billing/operations/pay-the-bill
- Create a cloud: https://yandex.cloud/en/docs/resource-manager/operations/cloud/create
- Create a folder: https://yandex.cloud/en/docs/resource-manager/operations/folder/create
- Create a service account: https://yandex.cloud/en/docs/iam/operations/sa/create
- Create and manage API keys: https://yandex.cloud/en/docs/iam/operations/authentication/manage-api-keys
- Vision OCR overview: https://yandex.cloud/en/docs/vision/concepts/ocr
- Vision OCR operation guide: https://yandex.cloud/en/docs/vision/operations/ocr
- Vision OCR sync API reference: https://yandex.cloud/en/docs/vision/ocr/api-ref/TextRecognition/recognize
- Legacy recognizeText API reference used by the current adapter: https://yandex.cloud/en/docs/vision/api-ref/Vision/recognizeText
- Vision pricing: https://yandex.cloud/en/docs/vision/pricing
- Current AI Studio Vision OCR overview: https://aistudio.yandex.ru/docs/en/vision/concepts/ocr/
- Current AI Studio OCR recognize API reference: https://aistudio.yandex.ru/docs/en/vision/ocr/api-ref/TextRecognition/recognize

## Local config files

Place secrets in plain text files under `config`:

- `config/yandex_key.txt`: one API key, no quotes.
- `config/api_key_yandex_studio.txt`: accepted project-local API key filename already used by this workspace.
- `config/yandex_key_id.txt`: optional API key identifier shown by Yandex Cloud. It is metadata, not the secret used in `Authorization`.
- `config/yandex_folder.txt`: one folder id, no quotes.

The repository contains `.example` files for both names. Do not paste the key into `llm_settings.yaml` or `tool_manifest.yaml`.

## Payment note

For a personal account, Yandex Cloud works through a normal billing account and paid cloud services. Vision OCR is billed by the Vision service pricing rules, not by LLM-style text tokens. After adding payment, use `Project tools -> Yandex OCR smoke test` to verify that the key, folder id, permissions, and billing access are all valid.

## Model note

One Yandex API key can be used with multiple OCR models. The key authenticates the request and ties it to the folder/billing context; the OCR model is selected per request through the `model` field.

The UI keeps these concerns separate:

- `Yandex API key`: selects the secret file.
- `Yandex mode`: selects the OCR model, for example `page`, `page-column-sort`, `table`, `handwritten`, `markdown`, or `math-markdown`.
