# Changelog

## 4.8.3 Beta + Houdini Model Import 0.5.0 — 12 октября 2026

Обновление с ранее опубликованной 4.0.0 Beta; промежуточные версии отдельно не перечислены.

### Blender
- Фоновый экспорт с прогрессом, оценкой времени и отменой.
- Обработка вложенных групп, Mix/Add Shader, IOR и transmission.
- Повторное использование материалов, устранение одинаковых текстур и локальный кэш.
- Читаемые имена файлов и опция проекции 3D-материалов на весь UV-тайл.
- Идентификатор ассета и номер ревизии в формате обмена schema 1.

### Houdini
- Отдельная панель библиотеки ассетов и установщик Windows.
- Проверка формата экспорта и диагностика отсутствующих текстур.
- Точные назначения материалов по путям USD.
- Обновление ранее импортированного ассета без дублирования сети.
- Сохранение предыдущих узлов при ошибке обновления.
- Сборка MaterialX с PBR-картами, AO, normal, opacity, emission, transmission, IOR и displacement.

ZIP опубликованы без изменения кода. Ограничения и статус проверки указаны в README.


## B2H Bridge v4.0.0 Beta

### Changes since v3.0.1

- Reworked the add-on into a clearer modular structure.
- Updated the Blender interface and organized export settings into focused sections.
- Improved texture handling and portable texture export.
- Added texture deduplication and cleanup of unreferenced exported textures.
- Improved bake stability, including controlled partial baking and GPU bake options.
- Improved reconstruction of materials for Houdini, including MaterialX-oriented output.
- Improved overall pipeline stability, diagnostics, and export feedback.

### Beta notes

- This is a work-in-progress beta release.
- Validate generated USD, texture paths, MaterialX files, and material assignments on your target Houdini setup before production use.