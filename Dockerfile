FROM python:3.6
MAINTAINER Zach White <skullydazed@gmail.com>

WORKDIR /qmk_api_tasks
COPY . /qmk_api_tasks
RUN pip3 install -r requirements.txt
RUN pip3 install git+git://github.com/qmk/qmk_compiler.git@master
ENV LC_ALL=C.UTF-8
ENV LANG=C.UTF-8
CMD ./run
