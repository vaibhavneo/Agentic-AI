"""Entry point: python run.py"""
from app import config
from web.app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=config.PORT, debug=True)
