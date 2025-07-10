#!/bin/bash
set -e

# If the files aren't in the user's terminal config then copy from the template
mkdir -p $USER_TERMINAL_CONFIG
for file in bashrc inputrc zshrc; do
    if [ ! -f $USER_TERMINAL_CONFIG/$file ]; then
        cp /root/terminal-config/$file-template $USER_TERMINAL_CONFIG/$file
    fi
done

# If there is no link to the inputrc then use this as a trigger to add
# hooks to all the files we reference
if [ ! -L "/root/.inputrc" ]; then
    ln -fs $USER_TERMINAL_CONFIG/inputrc /root/.inputrc
    for term in bash zsh; do
        cat <<EOF >> /root/.${term}rc
/root/terminal-config/ensure-user-terminal-config.sh
source ${USER_TERMINAL_CONFIG}/bashrc
EOF
    done
fi
