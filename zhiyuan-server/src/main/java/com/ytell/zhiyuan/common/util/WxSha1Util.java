package com.ytell.zhiyuan.common.util;

import javax.crypto.Cipher;
import javax.crypto.spec.IvParameterSpec;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.Base64;


public class WxSha1Util {

    // 生成签名
    public static String calSignature(String token, String timestamp, String nonce, String data) {
        String[] arr = new String[]{token, timestamp, nonce, data};
        Arrays.sort(arr);
        StringBuffer sb = new StringBuffer();
        for (int i = 0; i < arr.length; i++) {
            sb.append(arr[i]);
        }
        return getSha1(sb.toString());
    }

    // sha1签名算法
    public static String getSha1(String str) {
        if (str == null || str.length() == 0) {
            return null;
        }
        char hexDigits[] = {'0', '1', '2', '3', '4', '5', '6', '7', '8', '9', 'a', 'b', 'c', 'd', 'e', 'f'};

        try {
            MessageDigest mdTemp = MessageDigest.getInstance("SHA1");
            mdTemp.update(str.getBytes("UTF-8"));

            byte[] md = mdTemp.digest();
            int j = md.length;
            char buf[] = new char[j * 2];
            int k = 0;
            for (int i = 0; i < j; i++) {
                byte byte0 = md[i];
                buf[k++] = hexDigits[byte0 >>> 4 & 0xf];
                buf[k++] = hexDigits[byte0 & 0xf];
            }
            return new String(buf);
        } catch (Exception e) {
            return null;
        }
    }

    public static String decrypt(String encryptedText, String key) throws Exception {
        byte[] encryptedBytes = Base64.getDecoder().decode(encryptedText);
        byte[] keyBytes = Base64.getDecoder().decode(key + "=");
        byte[] ivBytes = new byte[16];
        System.arraycopy(keyBytes, 0, ivBytes, 0, 16);
        SecretKeySpec secretKeySpec = new SecretKeySpec(keyBytes, "AES");
        IvParameterSpec ivParameterSpec = new IvParameterSpec(ivBytes);
        Cipher cipher = Cipher.getInstance("AES/CBC/NOPADDING");
        cipher.init(Cipher.DECRYPT_MODE, secretKeySpec, ivParameterSpec);
        byte[] decryptedBytes = cipher.doFinal(encryptedBytes);
        int paddingLength = decryptedBytes[decryptedBytes.length - 1];
        byte[] unpaddedData = new byte[decryptedBytes.length - paddingLength];
        System.arraycopy(decryptedBytes, 0, unpaddedData, 0, unpaddedData.length);
        return new String(unpaddedData, StandardCharsets.UTF_8);
    }
}
