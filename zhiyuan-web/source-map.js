/* eslint-disable */
const path = require('path');
const fs = require('fs');

const TARGET_DIR = path.resolve(process.cwd(), '.next/static');

const getMaps = function (dir, ext = '.map') {
    let results = [];
    const list = fs.readdirSync(dir);
    list.forEach(file => {
        if (file === 'media') {
            return false;
        }
        file = `${dir}/${file}`;
        const stat = fs.statSync(file);
        if (stat && stat.isDirectory()) {
            results = results.concat(getMaps(file));
        }
        else if (path.extname(file) === ext) {
            results.push(path.resolve(__dirname, file));
        }
    });
    return results;
};

const deleteMaps = () => {
    try {
        console.log('删除source map');
        const sourceMaps = getMaps(TARGET_DIR);
        if (sourceMaps && sourceMaps.length === 0) {
            console.log('不存在source map');
        }
        sourceMaps.forEach(sourceMap => {
            fs.unlinkSync(sourceMap);
        });
    }
    catch (e) {
        console.log('删除source map失败');
        console.log(e);
        process.exit(1);
    }
};

deleteMaps();
