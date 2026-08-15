package com.testsapp.dto;

import com.testsapp.domain.NotificationChannel;
import com.testsapp.domain.NotificationType;

import java.time.LocalDateTime;

public record NotificationResponse(
        long id,
        long appointmentId,
        String customerEmail,
        String customerName,
        NotificationType type,
        NotificationChannel channel,
        String subject,
        String content,
        LocalDateTime createdAt
) {
}

