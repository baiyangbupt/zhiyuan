/* eslint-disable import/no-extraneous-dependencies */
import CryptoJS from 'crypto-js/crypto-js';
import qs from 'qs';

const key = 'qwer@WSX#$%&';
// stringSign是按照规则去拼接的字符串
export default function getSign(config) {
    const {data = {}, method = 'post', params = {}} = config;
    let payload = '';
    if (method === 'post') {
        payload = JSON.stringify(data);
    }
    else if (method === 'get') {
        payload = qs.stringify(params);
    }
    const hash = new CryptoJS.HmacSHA256(payload, key).toString();
    return hash;
}
