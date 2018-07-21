FROM python:3.6
MAINTAINER Zach White <skullydazed@gmail.com>

WORKDIR /
RUN git clone https://github.com/qmk/qmk_api_tasks.git
WORKDIR /qmk_api_tasks
RUN pip3 install git+git://github.com/qmk/qmk_compiler.git@master
RUN pip3 install -r requirements.txt
ENV LC_ALL=C.UTF-8
ENV LANG=C.UTF-8
CMD ./qmk_api_tasks.py
