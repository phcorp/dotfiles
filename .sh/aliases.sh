#!/bin/bash

alias updatedb='sudo /usr/libexec/locate.updatedb'
alias dotenv='export $(cat .env | grep -v ^# | xargs)'
