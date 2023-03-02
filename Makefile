
default:
	pip3 install -r requirements.txt
	./setup.py py2app

archive:
	cd dist && tar czvf OnAir.app.tgz *.app

clean:
	rm -rf dist build

format:
	black -l 140 .
