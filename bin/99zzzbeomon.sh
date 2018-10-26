#!/bin/bash
# Description: Beomon init script for compute_agent.py



script="${0##*/}"
node_number=${NODE:=${1:?"No Node Specified"}}



bpsh -m $node_number /opt/sam/beomon/bin/compute_agent.py --daemonize

status=$?

if [ $status != 0 ];then
  echo "Beomon startup failed!"
fi
