import {createApp} from 'vue';
import ElementPlus from 'element-plus';
import zhCn from 'element-plus/es/locale/lang/zh-cn';
import 'element-plus/dist/index.css';
import App from './app/App.vue';
import './app/theme.css';
import './app/typography.css';
createApp(App).use(ElementPlus,{locale:zhCn}).mount('#app');
