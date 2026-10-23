'use strict';
/* Voice input for the AI Journey Assistant: Speech → browser speech-to-text (Web Speech API) → editable transcript in
   the same text box → the same interpreter and planner as typed text. Nothing is recorded or uploaded by STREETWISE;
   in Chrome / Edge the browser's own speech service performs recognition. No server speech service is connected. */
const voice={rec:null,active:false,target:null,lang:'en-US'};
function speechSupported(){return Boolean(window.SpeechRecognition||window.webkitSpeechRecognition);}
function setupVoice(){
 const buttons=document.querySelectorAll('[data-mic]');
 if(!speechSupported()){buttons.forEach(b=>{b.disabled=true;b.title='Voice input is not supported in this browser (try Chrome, Edge or Safari). Type instead.';});$('voiceStatus').textContent='Voice: not supported in this browser — type instead.';return;}
 $('voiceLang').addEventListener('change',e=>{voice.lang=e.target.value;});
 buttons.forEach(b=>b.addEventListener('click',()=>voice.active?stopVoice():startVoice($(b.dataset.mic),b)));
}
function startVoice(target,button){
 const SR=window.SpeechRecognition||window.webkitSpeechRecognition;const rec=new SR();
 Object.assign(voice,{rec,active:true,target,button});
 rec.lang=voice.lang;rec.interimResults=true;rec.continuous=false;
 const base=target.value.trim()?target.value.trim()+' ':'';
 rec.onresult=e=>{let txt='';for(const r of e.results)txt+=r[0].transcript;target.value=base+txt;};
 rec.onerror=e=>{const msg={'not-allowed':'Microphone permission was denied.','no-speech':'No speech heard.','audio-capture':'No microphone found.','network':'The browser speech service is unreachable.'}[e.error]||`Voice error: ${e.error}`;
  $('voiceStatus').textContent=msg+' You can type instead.';};
 rec.onend=()=>{voice.active=false;button.classList.remove('recording');button.setAttribute('aria-pressed','false');
  if(!/error|denied|not/i.test($('voiceStatus').textContent))$('voiceStatus').textContent=target.value.trim()?'Transcript ready — edit it if needed, then send.':'Voice stopped.';target.focus();};
 try{rec.start();}catch(e){$('voiceStatus').textContent='Voice could not start: '+e.message;voice.active=false;return;}
 button.classList.add('recording');button.setAttribute('aria-pressed','true');$('voiceStatus').textContent=`Listening (${voice.lang==='zh-CN'?'中文':'English'})… tap again to stop.`;
}
function stopVoice(){voice.rec?.stop();}
