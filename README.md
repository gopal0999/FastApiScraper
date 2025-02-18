Please refer to the scraper_api.py file that is the main file

To run the server locally
uvicorn scraper_api:app --host 0.0.0.0 --port 8001 --reload


Requirements

intall python3

then clone the repo

go to the repo and from current directory run following command

source bin/activate

pip3 install requests fastapi tenacity bs4 redis uvicorn

then run the server locally using above command
