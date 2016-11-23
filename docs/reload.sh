inotifywait -mr source --exclude _build -e close_write -e create -e delete -e move --format '%w %e %T' --timefmt '%H%M%S' | while read file event tm; do
		current=$(date +'%H%M%S')
		delta=`expr $current - $tm`
		if [ $delta -lt 2 -a $delta -gt -2 ] ; then
			sleep 1  # спать 1 секунду на случай если не все файлы скопированы
			make html singlehtml
			xdotool search --name Chromium key --window %@ F5
		fi
	done
