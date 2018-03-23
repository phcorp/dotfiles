#!/bin/bash

# add color to terminal
export CLICOLOR=1
export LSCOLORS=ExFxBxDxCxegedabagacad

# define styles
export color_danger=$(echo -en "\e[1;41;97m")
export color_success=$(echo -en "\e[1;42;97m")
export color_warning=$(echo -en "\e[1;43;97m")
export color_notice=$(echo -en "\e[1;44;97m")
export color_reset=$(echo -en '\e[0m')