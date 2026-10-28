package com.ytell.zhiyuan.common.util;

import javax.crypto.SecretKeyFactory;
import javax.crypto.spec.PBEKeySpec;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.Arrays;
import java.util.Base64;

/** Self-describing username passwords; TOKEN/mobile credentials do not use this codec. */
public final class PasswordHashing {
    private static final String PREFIX = "$pbkdf2-sha256$";
    private static final int ITERATIONS = 600_000;
    private static final int SALT_BYTES = 16;
    private static final int HASH_BYTES = 32;
    private static final SecureRandom RANDOM = new SecureRandom();

    private PasswordHashing() { }

    public static boolean validPassword(String password) {
        return password != null && !password.trim().isEmpty() && password.length() <= 4096;
    }

    public static String hash(String password) {
        if (!validPassword(password)) {
            throw new IllegalArgumentException("invalid password");
        }
        byte[] salt = new byte[SALT_BYTES];
        RANDOM.nextBytes(salt);
        Base64.Encoder encoder = Base64.getEncoder().withoutPadding();
        return PREFIX + ITERATIONS + "$" + encoder.encodeToString(salt)
                + "$" + encoder.encodeToString(derive(password, salt, ITERATIONS));
    }

    public static boolean isLegacy(String stored) {
        // Reserve encoded-credential markers: malformed/unsupported hashes must
        // never fall back to plaintext equality (including pass-the-hash input).
        return validPassword(stored) && !stored.startsWith("$") && !stored.startsWith("{");
    }

    public static boolean matches(String password, String stored) {
        if (!validPassword(password) || stored == null || stored.isEmpty() || stored.length() > 255) {
            return false;
        }
        if (isLegacy(stored)) {
            return MessageDigest.isEqual(password.getBytes(StandardCharsets.UTF_8),
                    stored.getBytes(StandardCharsets.UTF_8));
        }
        if (!stored.startsWith(PREFIX)) {
            return false;
        }
        try {
            String[] fields = stored.split("\\$", -1);
            if (fields.length != 5) {
                return false;
            }
            int iterations = Integer.parseInt(fields[2]);
            // Bound work even when a stored credential is malformed or corrupt.
            if (iterations < 100_000 || iterations > 1_000_000) {
                return false;
            }
            byte[] salt = Base64.getDecoder().decode(fields[3]);
            byte[] expected = Base64.getDecoder().decode(fields[4]);
            return salt.length == SALT_BYTES && expected.length == HASH_BYTES
                    && MessageDigest.isEqual(expected, derive(password, salt, iterations));
        } catch (IllegalArgumentException exception) {
            return false;
        }
    }

    private static byte[] derive(String password, byte[] salt, int iterations) {
        char[] characters = password.toCharArray();
        PBEKeySpec spec = new PBEKeySpec(characters, salt, iterations, HASH_BYTES * 8);
        try {
            return SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256").generateSecret(spec).getEncoded();
        } catch (GeneralSecurityException exception) {
            throw new IllegalStateException("password hashing unavailable", exception);
        } finally {
            spec.clearPassword();
            Arrays.fill(characters, '\0');
        }
    }
}
