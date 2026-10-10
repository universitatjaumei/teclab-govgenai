import asyncio
import sys
import os
from pathlib import Path

# Añadir el directorio raíz al path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from server.app.database.db import init_server_db
from server.app.database.seeds import seed_all

async def main():
    print("Script de poblado de base de datos del servidor...")
    try:
        # Inicializar tablas si no existen
        await init_server_db()
        
        # Ejecutar seeds
        await seed_all()
        print("Poblado completado con éxito.")
    except Exception as e:
        print(f"Error durante el poblado: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
