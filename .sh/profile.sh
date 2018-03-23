#!/bin/bash

. "$HOME/.sh/aliases.sh"
. "$HOME/.sh/colors.sh"
. "$HOME/.sh/functions.sh"
. "$HOME/.sh/paths.sh"

# change terminal prompt
force_color_prompt=yes
export PS1="${debian_chroot:+($debian_chroot)}\[\033[01;32m\]\u@\h\[\033[00m\]:\[\033[01;34m\]\w\[\033[00m\]\$ "

# load completions if any are installed
[ -f /usr/local/etc/bash_completion ] && . /usr/local/etc/bash_completion

# set Default Editor
export EDITOR=/usr/bin/vi

# set default blocksize for ls, df, du
# from this: http://hints.macworld.com/comment.php?mode=view&cid=24491
export BLOCKSIZE=1k
