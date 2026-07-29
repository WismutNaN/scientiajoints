# Local environment notes

## Blender executable

На этой машине `blender.exe` найден здесь:

```text
E:\SteamLibrary\steamapps\common\Blender\blender.exe
```

Использовать этот путь для будущих headless integration smoke tests вместо поиска через `PATH`.

Пример команды:

```powershell
& 'E:\SteamLibrary\steamapps\common\Blender\blender.exe' --background --python path\to\smoke_test.py
```

Smoke test должен проверять минимум:

- импорт addon package;
- `register()` без исключений;
- наличие operator IDs;
- `unregister()` без исключений.
