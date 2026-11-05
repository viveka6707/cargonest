"""Initialize CargoNest MySQL database and tables."""
from app import init_db
if __name__ == '__main__':
    init_db()
    print('CargoNest MySQL database initialized successfully.')
