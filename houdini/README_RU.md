# B2H Model Import 0.5.0

Расширение Houdini 21 для импорта моделей, материалов и текстур,
экспортированных из Blender через **B2H Bridge 4.8.1 Beta** или новее.

## Возможности

- импорт USD в Solaris с редактируемой SOP-сетью;
- Karma MaterialX для Base Color, AO, Roughness, Metallic, Normal, Opacity,
  Emission, Transmission, IOR и Displacement;
- точные назначения материалов по USD-примам;
- повторный импорт без размножения нод;
- сохранение предыдущего рабочего импорта, если обновление завершилось ошибкой;
- проверка манифеста и понятные статусы импорта;
- фоновое сканирование библиотеки и индикатор прогресса.

## Быстрая установка на Windows

1. Распакуйте архив полностью.
2. Закройте Houdini.
3. Запустите `install_windows.bat`.
4. Перезапустите Houdini.
5. Откройте **Windows → New Pane Tab Type → B2H Model Import v0.5.0**.

Установщик находит **все версии Houdini** в обычных `Documents`, в OneDrive
и в `Program Files`. Package-файл и Python Panel устанавливаются для каждой
найденной версии. Общие файлы программы устанавливаются один раз в:

`%LOCALAPPDATA%\B2H\ModelImport\0.5.0`

Если папки не определились автоматически, можно передать одну или несколько:

```powershell
powershell -ExecutionPolicy Bypass -File .\install_windows.ps1 `
  -HoudiniUserDir "C:\Users\USERNAME\Documents\houdini20.5", `
                  "C:\Users\USERNAME\Documents\houdini21.0"
```

Установщик сохраняет заменяемые package/pypanel-файлы в папке `b2h_backup`
внутри каждой пользовательской папки Houdini.

## Ручная установка

1. Скопируйте папку `B2H_Model_Import` в постоянное место.
2. Скопируйте `b2h_asset_library.pypanel` в
   `<houdini user dir>/python_panels`.
3. Скопируйте `B2H_Model_Import.package.example.json` в
   `<houdini user dir>/packages/B2H_Model_Import.json`.
4. Замените `C:/PATH/TO/B2H_Model_Import` на реальный путь.
5. Перезапустите Houdini.

## Использование

1. В Blender экспортируйте модель через B2H Bridge.
2. Для объектов с несколькими материалами оставьте включённым
   **Split Meshes By Material**.
3. В Houdini выберите папку экспорта и нажмите **Refresh**.
4. Выберите ассет и нажмите **Import / Update Selected**.

Повторный импорт ассета с тем же `asset_id` обновляет только принадлежащие ему
B2H-ноды. Пользовательские ноды в `/stage` не удаляются.

## Совместимость

- протестировано: Houdini 21.0.559;
- регрессионные тесты Blender пройдены в Blender 5.1;
- формат манифеста: B2H schema v1;
- ОС установщика: Windows 10/11.

## Проверка для разработчиков

```powershell
& "C:\Program Files\Side Effects Software\Houdini 21.0.559\bin\hython.exe" `
  .\tests\test_houdini_import.py
```

## Лицензия

MIT. См. `LICENSE`.
