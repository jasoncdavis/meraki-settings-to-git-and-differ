FROM python:3.9-slim-buster

COPY ./docker/python/install-packages.sh /project/
RUN chmod +x /project/install-packages.sh

RUN /project/install-packages.sh

ADD ./requirements.txt /project/requirements.txt
RUN pip install -r /project/requirements.txt #only re-executed if the file changes

ADD ./src /project/code
ADD ./html /project/code/html
ADD ./images /project/code/images

RUN npm install -g diff2html-cli

CMD tail -f /dev/null