const sharp=require('sharp'),fs=require('fs'),path=require('path');
const root=path.resolve(__dirname,'..'),src=path.resolve(root,'../gdg-artwork');
(async()=>{for(const file of fs.readdirSync(src).filter(f=>f.endsWith('.png'))){await sharp(path.join(src,file)).resize({width:file==='acceptance-seal.png'?420:1080,withoutEnlargement:true}).png({palette:true,colours:256,quality:90,effort:10}).toFile(path.join(root,'assets',file));console.log(file,fs.statSync(path.join(root,'assets',file)).size)}})();
