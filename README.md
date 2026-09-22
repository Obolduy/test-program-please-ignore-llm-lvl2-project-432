# ИИ-генератор карточки товара

[![hexlet-check](https://github.com/Obolduy/test-program-please-ignore-llm-lvl2-project-432/actions/workflows/hexlet-check.yml/badge.svg)](https://github.com/Obolduy/test-program-please-ignore-llm-lvl2-project-432/actions)

Сервис принимает доки в pdf, docx, xlsx, строит по ним поисковый индекс
и собирает черновик карточки товара: характеристики со ссылками на фрагменты документов,
список недостающих полей и уровень уверенности.

[![asciicast](https://asciinema.org/a/leZh1YsjweFgRazO.svg)](https://asciinema.org/a/leZh1YsjweFgRazO)

## Требования

[uv](https://docs.astral.sh/uv/), Docker Compose и сервер моделей с API в формате
OpenAI Ollama, LM Studio или OpenRouter.

## Запуск

```bash
cp .env.example .env   
make infra           
make setup            
make api
make worker
curl localhost:8000/ready
```

## Использование

```bash
curl -F file=@data/blender_passport.pdf localhost:8000/documents
curl localhost:8000/documents
curl -X POST localhost:8000/generate-card -H 'Content-Type: application/json' \
  -d '{"document_ids": ["id документа"], "product_hint": "блендер"}'
curl localhost:8000/jobs/<id задачи>
curl -X POST localhost:8000/workflows/<id задачи>/approve
curl -X POST localhost:8000/workflows/<id задачи>/request-changes
```

## Разработка

```bash
make test   
make lint
make eval    
make help   
```

Результат ласт прогона в [docs/report.md](docs/report.md),
принятые решения в [docs/decisions.md](docs/decisions.md).
