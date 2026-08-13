package com.testsapp.repository;
import com.testsapp.domain.Appointment;
import com.testsapp.domain.AppointmentStatus;
import org.springframework.stereotype.Repository;
import java.time.LocalDateTime;
import java.util.Comparator;
import java.util.List;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentMap;
import java.util.concurrent.atomic.AtomicLong;
@Repository
public class AppointmentRepository {
    private final ConcurrentMap<Long, Appointment> storage = new ConcurrentHashMap<>();
    private final AtomicLong idSequence = new AtomicLong(1);
    public Appointment save(Appointment appointment) {
        if (appointment.getId() == 0) {
            appointment.assignId(idSequence.getAndIncrement());
        }
        storage.put(appointment.getId(), appointment);
        return appointment;
    }
    public Optional<Appointment> findById(long id) {
        return Optional.ofNullable(storage.get(id));
    }
    public List<Appointment> findAll() {
        return storage.values().stream()
                .sorted(Comparator.comparing(Appointment::getStartTime).thenComparingLong(Appointment::getId))
                .toList();
    }
    public List<Appointment> findByCustomerEmail(String customerEmail) {
        String normalized = normalize(customerEmail);
        return storage.values().stream()
                .filter(item -> normalize(item.getCustomerEmail()).equals(normalized))
                .sorted(Comparator.comparing(Appointment::getStartTime).thenComparingLong(Appointment::getId))
                .toList();
    }
    public List<Appointment> findByStatus(AppointmentStatus status) {
        return storage.values().stream()
                .filter(item -> item.getStatus() == status)
                .sorted(Comparator.comparing(Appointment::getStartTime).thenComparingLong(Appointment::getId))
                .toList();
    }
    public List<Appointment> findFutureActiveByCustomer(String customerEmail, LocalDateTime now) {
        String normalized = normalize(customerEmail);
        return storage.values().stream()
                .filter(item -> normalize(item.getCustomerEmail()).equals(normalized))
                .filter(item -> item.getStatus() == AppointmentStatus.SCHEDULED)
                .filter(item -> item.getStartTime().isAfter(now))
                .sorted(Comparator.comparing(Appointment::getStartTime).thenComparingLong(Appointment::getId))
                .toList();
    }
    public List<Appointment> findFutureActiveByService(long serviceOfferId, LocalDateTime now) {
        return storage.values().stream()
                .filter(item -> item.getServiceOfferId() == serviceOfferId)
                .filter(item -> item.getStatus() == AppointmentStatus.SCHEDULED)
                .filter(item -> item.getStartTime().isAfter(now))
                .sorted(Comparator.comparing(Appointment::getStartTime).thenComparingLong(Appointment::getId))
                .toList();
    }
    public List<Appointment> findScheduledOnDate(java.time.LocalDate date) {
        return storage.values().stream()
                .filter(item -> item.getStatus() == AppointmentStatus.SCHEDULED)
                .filter(item -> item.getStartTime().toLocalDate().equals(date))
                .sorted(Comparator.comparing(Appointment::getStartTime).thenComparingLong(Appointment::getId))
                .toList();
    }
    public List<Appointment> findUpcoming(LocalDateTime now) {
        return storage.values().stream()
                .filter(item -> item.getStatus() == AppointmentStatus.SCHEDULED)
                .filter(item -> item.getStartTime().isAfter(now))
                .sorted(Comparator.comparing(Appointment::getStartTime).thenComparingLong(Appointment::getId))
                .toList();
    }
    private String normalize(String value) {
        return value == null ? "" : value.trim().toLowerCase(java.util.Locale.ROOT);
    }
}
