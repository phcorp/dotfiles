#!/bin/bash

# stop execution if command returns an error
function safe_run() {
  typeset cmnd="$*"
  typeset ret_code
  echo cmnd=$cmnd
  eval $cmnd
  ret_code=$?
  if [ $ret_code != 0 ]; then
    printf "Error : [%d] when executing command: '$cmnd'" $ret_code
    exit $ret_code
  fi
}

# split terminal
function tsplit() {
	TSPLIT_WINDOWS=${1:-2}
	COMMAND="tmux new-session \"tmux new-window \;"
	for TSPLIT_WINDOW in `seq 2 $TSPLIT_WINDOWS`
	do
		COMMAND="$COMMAND split-window -d \;"
	done
	COMMAND="$COMMAND next-layout \; set-window-option synchronize-panes on\""
	eval $COMMAND
}

# print all available colors
function color_palette {
	for clbg in {40..47} {100..107} 49 ; do
		#Foreground
		for clfg in {30..37} {90..97} 39 ; do
			#Formatting
			for attr in 0 1 2 4 5 7 ; do
				#Print the result
				echo -en "\e[${attr};${clbg};${clfg}m ^[${attr};${clbg};${clfg}m \e[0m"
			done
			echo #Newline
		done
	done
}

# symfony alias
function symfony {
	if [ -e "bin/console" ]; then
	    php bin/console -v $*;
	    return;
	fi
	if [ -e "app/console" ]; then
	    php app/console -v $*;
	    return;
	fi
    echo "${color_danger}Symfony console script was not found${color_reset}" >&2;
}

# use ssh key
function ssh-use-key {
	eval "$(ssh-agent -s)" && ssh-add -K "$*"
}

# rebase upstream
function git-sync {
	upstream=${1:-upstream}
	origin=${2:-origin}
	branch=${3:-master}
	git checkout "$branch"
	git fetch "$upstream"
	git reset --hard "$upstream/$branch"
	git push -f "$origin" "$branch"
}
