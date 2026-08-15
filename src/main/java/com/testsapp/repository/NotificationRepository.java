package com.testsapp.repository;

import com.testsapp.domain.NotificationMessage;
import com.testsapp.domain.NotificationType;
import org.springframework.stereotype.Repository;

import java.time.LocalDate;
import java.util.Comparator;
import java.util.List;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentMap;
import java.util.concurrent.atomic.AtomicLong;

@Repository
public class NotificationRepository {
    private final ConcurrentMap<Long, NotificationMessage> storage = new ConcurrentHashMap<>();
    private final AtomicLong idSequence = new AtomicLong(1);

    public NotificationMessage save(NotificationMessage message) {
        if (message.getId() == 0) {
            message.assignId(idSequence.getAndIncrement());
        }
        storage.put(message.getId(), message);
        return message;
    }

    public List<NotificationMessage> findAll() {
        return storage.values().stream()
                .sorted(Comparator.comparing(NotificationMessage::getCreatedAt).thenComparingLong(NotificationMessage::getId))
                .toList();
    }

    public boolean hasReminderForAppointmentOnDate(long appointmentId, LocalDate date) {
        return storage.values().stream()
                .filter(item -> item.getAppointmentId() == appointmentId)
                .filter(item -> item.getType() == NotificationType.APPOINTMENT_REMINDER)
                .anyMatch(item -> item.getCreatedAt().toLocalDate().equals(date));
    }
}

