// Check availability without downloading the APK or sending account credentials.
fetch('/downloads/olamide-medical.apk.sha256',{credentials:'omit',cache:'no-store'})
 .then(response=>{if(!response.ok)throw Error('pending');return response.text()})
 .then(()=>{document.getElementById('mobile-status').textContent='Android download is available.'})
 .catch(()=>{const link=document.getElementById('apk-download');link.removeAttribute('href');link.removeAttribute('download');link.setAttribute('aria-disabled','true');link.textContent='Android download pending deployment';document.getElementById('mobile-status').textContent='The Android package has not been installed on this server yet. Use the hospital website in the meantime.'});
