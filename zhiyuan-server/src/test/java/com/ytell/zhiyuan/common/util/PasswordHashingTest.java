package com.ytell.zhiyuan.common.util;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class PasswordHashingTest {
    @Test
    void hashesUseIndependentSaltsAndFitTheCredentialColumn() {
        String first = PasswordHashing.hash("new-password");
        String second = PasswordHashing.hash("new-password");
        assertNotEquals(first, second);
        assertTrue(first.startsWith("$pbkdf2-sha256$600000$"));
        assertTrue(first.length() <= 255);
        assertFalse(PasswordHashing.isLegacy(first));
        assertTrue(PasswordHashing.matches("new-password", first));
        assertTrue(PasswordHashing.matches("new-password", second));
        assertFalse(PasswordHashing.matches("wrong-password", first));
        assertFalse(PasswordHashing.matches(first, first));
    }

    @Test
    void missingOrMalformedHashesNeverFallBackToPlaintextEquality() {
        for (String stored : new String[] {null, "", "$pbkdf2-sha256$broken", "$2a$unsupported",
                "{bcrypt}broken", "$pbkdf2-sha256$2147483647$bad$bad", "$pbkdf2-sha256$0$bad$bad"}) {
            assertFalse(PasswordHashing.matches(stored, stored));
            assertFalse(PasswordHashing.matches("password", stored));
        }
        for (String password : new String[] {null, "", "  "}) {
            assertThrows(IllegalArgumentException.class, () -> PasswordHashing.hash(password));
            assertFalse(PasswordHashing.matches(password, "legacy-password"));
        }
    }

    @Test
    void legacyPlaintextMatchIsExplicitAndCaseSensitive() {
        assertTrue(PasswordHashing.isLegacy("Old-Password"));
        assertTrue(PasswordHashing.matches("Old-Password", "Old-Password"));
        assertFalse(PasswordHashing.matches("old-password", "Old-Password"));
    }
}
