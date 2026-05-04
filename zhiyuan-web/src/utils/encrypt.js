import {isClient} from '@/constants/constants';

const PUBLIC_KEY = `MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDGjoM+ytfFfnLQnMoQNFvfhxNZ
20vq7mZA3/1RoJou6H9RMj5WKddLqsPs/0TbZJl7PZizGQwRRg6ObikmQiqpIFlR
XHkZL79bggTzKh/tBE1ZGFzyPe72/oei0alRfrvXiEBffK2xwdSgVp8t4vI61Pcq
KmXJpmkmnxwCL445IQIDAQAB`;

let instance;

// jsencrypt会取navigator的属性,ssr的时候会报错
if (isClient) {
    /* eslint-disable @typescript-eslint/no-var-requires */
    const {JSEncrypt} = require('jsencrypt');
    instance = new JSEncrypt();
    instance.setPublicKey(PUBLIC_KEY);
}

export default function rsaEncrypt(content = '') {
    return instance ? instance.encrypt(content) : content;
}
