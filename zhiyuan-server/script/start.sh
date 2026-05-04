#!/bin/bash -x
rm -f tpid
app_name=zhiyuan-server
app_home=/root/work/$app_name
package=$app_home/$app_name.jar
config_file=$app_home/application-online.yml
log_config_file=$app_home/logback-spring.xml
args=${ARGS:-"-Xms2048m -Xmx2048m"}
GC_LOG_FILE=$app_home/logs/${app_name}-gc.log

nohup java $args -Dapp_name=$app_name \
           -Dspring.profiles.active=online \
           -Dspring.config.location=$config_file \
           -Dlogging.config=$log_config_file \
           -verbose:gc -XX:+PrintGCDetails -XX:+PrintGCDateStamps -XX:MetaspaceSize=300m -Xloggc:$GC_LOG_FILE \
           -XX:+UseGCLogFileRotation -XX:NumberOfGCLogFiles=10 -XX:GCLogFileSize=10M \
           -jar $package  > /dev/null 2>&1 &

echo $! > tpid